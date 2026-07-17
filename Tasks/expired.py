"""
Weekly expiry checker.

Three escalating tiers, cheapest first — most jobs should resolve at tier 1
and never touch Playwright or the LLM:

  Tier 1 (cheap):   HEAD, falling back to a small GET, against apply_url.
                     Catches dead status codes (404/410) and redirects to
                     known "expired" URL shapes almost for free. Known
                     JS-rendered ATS domains (Workday, Ashby, etc.) skip
                     text classification here entirely and escalate straight
                     to tier 2 — their raw HTML is an empty SPA shell
                     regardless of whether the listing is alive or dead, so
                     trusting it produces confident false negatives.
  Tier 2 (scrape):   Only runs if tier 1 is inconclusive (e.g. a JS-rendered
                     ATS page that always 200s). Reuses Pirate.scrape_apply_url
                     — the same Playwright scraper the enricher uses — and
                     Pirate.classify_scraped_text() to catch "posting closed"
                     wording that a raw HTTP check can't see.
  Tier 3 (LLM):      Only runs if tier 2's scraped text still doesn't clearly
                     say expired/garbage. Calls provider.check_expired() — a
                     dedicated, narrow prompt that takes only the scraped
                     text and asks a single yes/no question, no Job object
                     and no other fields extracted or written.

Unlike JobEnricher, this never fills in missing fields — it only ever
flips status -> "expired". Jobs it can't confidently classify at any tier
are left untouched, and already-expired jobs are excluded by the query
itself, so re-running this weekly is safe and idempotent.
"""

import asyncio
from datetime import timezone
import datetime
import uuid
from typing import Optional

import aiohttp,threading
from bs4 import BeautifulSoup
from tqdm import tqdm
from Utils.constants import Config
from Refine.llm import LLMProvider, OllamaProvider
from Service.Scrapper import Pirate
from Service.db import JobDatabase
from Utils.notify import notify_discord
from datetime import datetime, timezone


class ExpiryChecker:
    """Escalating, expired-only re-validation pass over non-expired jobs."""

    TIMEOUT = aiohttp.ClientTimeout(total=8)
    DEAD_STATUS_CODES = {404, 410}
    GET_BYTE_LIMIT = 20_000  # tier 1's GET fallback only sniffs the first N bytes
    USER_AGENT = "Mozilla/5.0 (compatible; LibraExpiryChecker/1.0)"

    DEFAULT_HTTP_CONCURRENCY = 10   # tier 1 — cheap, can run wide
    DEFAULT_HEAVY_CONCURRENCY = 2   # tiers 2/3 — Playwright + LLM, keep narrow

    # Platforms that render the job page client-side via JS. A plain GET on
    # these returns an (almost) empty SPA shell — no "job not found" text,
    # but also no real posting content — regardless of whether the listing
    # is alive or dead. Classifying that raw shell as "ok" is a confident
    # false negative (see: 4/5 Workday/Ashby jobs misreported as active in
    # a real run). Skip tier 1's text classification for these domains and
    # go straight to tier 2 (Playwright), which actually renders the page.
    SPA_ONLY_DOMAINS = (
        "myworkdayjobs.com",
        "ashbyhq.com",
        "greenhouse.io",
        "lever.co",
        "smartrecruiters.com",
    )

    def __init__(
        self,
        provider: Optional[LLMProvider] = None,
        use_llm: bool = True,
        llm_delay: float = 0.5,
    ):
        self.http_semaphore = asyncio.Semaphore(self.DEFAULT_HTTP_CONCURRENCY)
        self.heavy_semaphore = asyncio.Semaphore(self.DEFAULT_HEAVY_CONCURRENCY)
        self.pirate = Pirate()
        self.use_llm = use_llm
        self.provider = provider or (OllamaProvider() if use_llm else None)
        self.llm_delay = llm_delay

        self.metrics = {
            "checked": 0,
            "newly_expired": 0,
            "failed": 0,
            "blocked": 0,
            "resolved_tier1": 0,
            "resolved_tier2": 0,
            "resolved_tier3": 0,
        }

    # ─── Tier 1: cheap HTTP check ──────────────────────────────────────────
   
    def _is_spa_only_domain(self, url: str) -> bool:
        return any(domain in url for domain in self.SPA_ONLY_DOMAINS)

   
    def _redirect_looks_expired(self, original_url: str, final_url: str) -> bool:
        if final_url == original_url:
            return False
        # Reuses whatever pattern set Pirate already maintains for expired-URL
        # detection, so this stays a single source of truth with the enricher.
        return self.pirate._is_known_expired_redirect(final_url)

    @staticmethod
    def _visible_text(html: str) -> str:
        """
        Strip tags/scripts/styles so classify_scraped_text() is judging the
        same kind of input here as it does everywhere else (Pirate always
        hands it rendered or BeautifulSoup-extracted text, never raw markup).
        Raw HTML is long and script/style-heavy enough to dodge both the
        "garbage" length check and every phrase match by accident.
        """
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["nav", "footer", "script", "style", "header"]):
            tag.decompose()
        return soup.get_text(separator=" ")
 
    async def _cheap_check(self, session: aiohttp.ClientSession, url: str) -> Optional[bool]:
        """True/False if confident, None if inconclusive (escalate to tier 2)."""
        headers = {"User-Agent": self.USER_AGENT}

        try:
            async with session.head(
                url, allow_redirects=True, timeout=self.TIMEOUT, headers=headers
            ) as resp:
                if resp.status in self.DEAD_STATUS_CODES:
                    return True
                if self._redirect_looks_expired(url, str(resp.url)):
                    return True
                if resp.status == 200:
                    # A 200 alone isn't proof of life — many ATS pages 200 a
                    # "posting closed" shell. Fall through to a text sniff via
                    # GET rather than trusting the status code in isolation.
                    pass
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass  # some ATSes reject HEAD outright — fall through to GET

        try:
            async with session.get(
                url, allow_redirects=True, timeout=self.TIMEOUT, headers=headers
            ) as resp:
                if resp.status in self.DEAD_STATUS_CODES:
                    return True
                if self._redirect_looks_expired(url, str(resp.url)):
                    return True
                if resp.status != 200:
                    return None  # ambiguous status — don't guess

                # Known JS-rendered ATS platforms: their raw HTML is a near-
                # empty SPA shell whether the job is live or dead. There is
                # nothing here worth classifying — escalate straight to
                # tier 2, which can actually render the page.
                if self._is_spa_only_domain(str(resp.url)):
                    return None

                chunk = await resp.content.read(self.GET_BYTE_LIMIT)
                raw = chunk.decode(errors="ignore")
                text = self._visible_text(raw)
                status = self.pirate.classify_scraped_text(text)
                if status == "expired":
                    return True
                if status == "garbage":
                    # Not enough real text to go on either way — likely a
                    # JS-rendered page we don't have a domain rule for yet.
                    # Escalate rather than assume.
                    return None
                return False
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            Config.logger.warning(f"Tier 1 check failed for {url}: {e}")
            return None

    # ─── Tiers 2/3: Playwright scrape, then LLM — expired signal only ─────

   
    async def _deep_check(self, apply_url: str) -> Optional[bool]:
        """
        Escalation path for jobs tier 1 couldn't resolve. Runs the same
        Playwright scrape the enricher uses, then the LLM if needed — but
        only ever looks at the job_expired signal via check_expired(), never
        fills other fields and never needs a Job object.
        """
        scraped = await self.pirate.scrape_apply_url(apply_url)  # type: ignore
        
        if scraped is None:
            return None

        if isinstance(scraped, dict):
            # A block (403/429) is NOT evidence the job is expired — just
            # that this scrape attempt was refused. Count it separately so
            # "site is blocking us" doesn't get buried in a generic failed
            # count, and definitely doesn't get treated as expired.
            if scraped.get("blocked"):
                self.metrics["blocked"] += 1
                Config.logger.warning(
                    f"Scrape blocked (HTTP {scraped.get('status_code')}) for {apply_url}"
                )
                return None

            # Structured (schema.org JobPosting JSON-LD) data — treat as
            # authoritative, same as the enricher does. Only count this as
            # tier-2-resolved if it actually yields a verdict; if job_expired
            # is missing/None, this still falls through to the LLM and tier 3
            # gets the credit.
            if scraped.get("job_expired"):
                self.metrics["resolved_tier2"] += 1
                return True
            if scraped.get("job_expired") is False:
                self.metrics["resolved_tier2"] += 1
                return False
            text_for_llm = scraped.get("description")
        else:
            status = self.pirate.classify_scraped_text(scraped)
            if status == "expired":
                self.metrics["resolved_tier2"] += 1
                return True
            if status == "garbage":
                return None  # still nothing usable — give up rather than guess
            text_for_llm = scraped

        if not (self.use_llm and self.provider and text_for_llm):
            return None

        # Dedicated, narrow LLM call — just the expired signal, no Job
        # object needed and no other fields extracted or written.
        is_expired = self.provider.check_expired(text_for_llm)
        if is_expired is None:
            return None  # model gave no clear verdict — stay inconclusive
        self.metrics["resolved_tier3"] += 1
        return is_expired

    # ─── Orchestration ─────────────────────────────────────────────────────

    async def _check_one(self, session: aiohttp.ClientSession, job: dict) -> tuple[uuid.UUID, Optional[bool]]:
        job_id = job.get("id")
        url = job.get("apply_url")
        if not url:
            return job_id, None  # type: ignore

        async with self.http_semaphore:
            result = await self._cheap_check(session, url)
        if result is not None:
            self.metrics["resolved_tier1"] += 1
            return job_id, result  # type: ignore

        async with self.heavy_semaphore:
            result = await self._deep_check(url)
            if self.use_llm:
                await asyncio.sleep(self.llm_delay)  # respect free-tier/rate limits
        return job_id, result  # type: ignore


    async def run(self, db: "JobDatabase") -> dict:
        jobs = await db.select(
            table="job_list",
            filters={"status": "active"},
            columns=["id", "apply_url"],
        )

        Config.logger.info(f"Weekly expiry check: {len(jobs)} non-expired jobs to check")

        async with aiohttp.ClientSession() as session:
            tasks = [asyncio.create_task(self._check_one(session, job)) for job in jobs]

            results = []
            with tqdm(total=len(tasks), desc="Checking jobs", unit="job", ncols=100) as pbar:
                stop_ticker = threading.Event()
                ticker = threading.Thread(
                    target=lambda: [
                        pbar.refresh() for _ in iter(lambda: stop_ticker.wait(1), True)
                    ],
                    daemon=True,
                )
                ticker.start()

                for coro in asyncio.as_completed(tasks):
                    job_id, is_expired = await coro
                    results.append((job_id, is_expired))
                    pbar.update(1)
                    pbar.set_postfix({
                        "t1": self.metrics["resolved_tier1"],
                        "t2": self.metrics["resolved_tier2"],
                        "t3": self.metrics["resolved_tier3"],
                        "blocked": self.metrics["blocked"],
                    })

                stop_ticker.set()
                ticker.join()

        newly_expired_ids = []
        for job_id, is_expired in results:
            self.metrics["checked"] += 1
            if is_expired is None:
                self.metrics["failed"] += 1
            elif is_expired:
                self.metrics["newly_expired"] += 1
                newly_expired_ids.append(job_id)

        if newly_expired_ids:
            await db.raw(
                sql="UPDATE job_list SET status = 'expired' WHERE id = ANY($1)",
                params=[newly_expired_ids],
            )

        Config.logger.info(
            f"Weekly expiry check done — checked: {self.metrics['checked']}, "
            f"newly expired: {self.metrics['newly_expired']}, "
            f"failed: {self.metrics['failed']}, "
            f"blocked: {self.metrics['blocked']} "
            f"(tier1: {self.metrics['resolved_tier1']}, "
            f"tier2: {self.metrics['resolved_tier2']}, "
            f"tier3: {self.metrics['resolved_tier3']})"
        )
        return self.metrics
    
async def run_weekly_expiry_check() -> None:
    """Entry point for the scheduled (cron/systemd timer) job."""
    db = await JobDatabase.create()
    checker = ExpiryChecker()
    results = await checker.run(db)
    embed = {
        "title": "Weekly Expiry Check ",
        "color": 0x5865F2 if not results['failed'] and not results['blocked'] else 0xE67E22,
        "fields": [
            {"name": "Checked", "value": str(results['checked']), "inline": True},
            {"name": "Newly Expired", "value": str(results['newly_expired']), "inline": True},
            {"name": "Failed", "value": str(results['failed']), "inline": True},
            {"name": "Blocked", "value": str(results['blocked']), "inline": True},
            {"name": "Tier 1", "value": str(results['resolved_tier1']), "inline": True},
            {"name": "Tier 2", "value": str(results['resolved_tier2']), "inline": True},
            {"name": "Tier 3", "value": str(results['resolved_tier3']), "inline": True},
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    notify_discord(embed=embed)
    
  


if __name__ == "__main__":
    
    asyncio.run(run_weekly_expiry_check())