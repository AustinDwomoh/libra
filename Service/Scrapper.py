from bs4 import BeautifulSoup
from typing import Optional, Union

from Utils.constants import Config
import json, requests, asyncio, re
from dataclasses import dataclass

@dataclass
class ScrapeResult:
    raw_text: str = ""      # full cleaned text (cookies stripped), used for regex
    trimmed_text: str = ""  # narrowed to Responsibilities→Qualifications window, used for description + LLM

class Pirate:
 
    def __init__(self):
        self._COOKIE_NOTICE_RE = re.compile(
            r"(accept cookies from .{0,50}browser.*)$",  # existing pattern, keep as one option
            re.IGNORECASE | re.DOTALL,
        )
        self._COOKIE_BANNER_TAIL_RE = re.compile(
            r"(decline all\s+accept all\s*)$",
            re.IGNORECASE,
        )
        self. _DESC_START_MARKERS = ["responsibilities", "about the role", "about the team", "what you'll do"]
        self._DESC_END_MARKERS = ["job information", "why join us", "diversity & inclusion", "equal employment opportunity", "accommodation"]
        self._COOKIE_TAIL_SIGNALS = [
            "accept cookies from",
            "we use cookies",
            "this site uses cookies",
            "manage your cookies",
            "cookie policy",
            "cookies to provide",
        ]
        self._EXPIRED_SIGNALS = [s.lower() for s in [
            "no longer available",
            "position has been filled",
            "listing has expired",
            "job not found",
            "no longer accepting",
            "this job has expired",
            "posting has been removed",
            "unable to find this job",
            "the page you are looking for doesn't exist",
            "the job you are looking for is no longer available",
            "this job posting has expired",
            "does not exist or has been removed",
            "doesn't exist",
            # Removed bare "no longer" and "expired" — both produce false
            # positives on real, live postings (e.g. "valid passport that
            # has not expired" is a common visa/travel requirement bullet).
        ]]

        self._GARBAGE_SIGNALS = [
            "sign in to apply",
            "log in to continue",
            "please sign in",
            "please enable javascript",
            "just a moment",  # cloudflare challenge page, served with a real 200
            "checking your browser",  # cloudflare challenge page, served with a real 200
            "are you a human",  # cloudflare
            "workday is currently unavailable",  # Workday's own outage page,
            "we are experiencing a service interruption",  # not the actual posting
            # Removed bare "sign in" / "log in" — these appear in legitimate
            # job descriptions for any auth/identity-related role.
            # Removed "403 forbidden" / "404 not found" text signals — dead
            # code in practice. A real 403/404 status raises via
            # raise_for_status() (requests) or is visible on the Playwright
            # response object before this classifier ever sees page text; by
            # the time text classification runs, the status was already 200.
            # Detecting a block/dead-link is now handled at the status-code
            # level in scrape_apply_url instead (see BLOCKED_STATUS_CODES).
        ]

        self._SITE_EXPIRED_URL_PATTERNS = {
            "linkedin.com": [r"trk=expired_jd_redirect", r"/jobs/[\w-]+-jobs\?"],
            "myworkdayjobs.com": [r"/error", r"/notfound", r"sessionTimedOut"],
        }

        # Status codes that mean "the site actively blocked this request"
        # (bot detection, rate limiting) — NOT evidence the job is expired.
        # These are surfaced distinctly so callers don't conflate "we got
        # blocked" with "the listing is dead" or "something is broken".
        self.BLOCKED_STATUS_CODES = {403, 429}

        # A bare UA string with no other headers is a dead giveaway of
        # non-browser traffic to even basic bot detection. This won't
        # defeat a determined WAF (Cloudflare/PerimeterX-style JS challenges,
        # TLS/JA3 fingerprinting) — nothing short of a real browser can — but
        # it avoids being trivially flagged by simpler header-sniffing checks.
        self._HEADERS = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        }
        
    def _trim_to_description(self, text: str) -> str:
        lowered = text.lower()
        start = next((lowered.find(m) for m in self._DESC_START_MARKERS if m in lowered), -1)
        if start == -1:
            return text
        end_candidates = [lowered.find(m, start) for m in self._DESC_END_MARKERS if lowered.find(m, start) != -1]
        end = min(end_candidates) if end_candidates else len(text)
        return text[start:end].strip()
    
    def _is_known_expired_redirect(self, final_url: str) -> bool:
        for domain, patterns in self._SITE_EXPIRED_URL_PATTERNS.items():
            if domain in final_url:
                if any(re.search(p, final_url) for p in patterns):
                    return True
        return False

    def _extract_jobposting_jsonld(self, html: str) -> Optional[dict]:
        """
        Look for a schema.org JobPosting JSON-LD block in the page source.
        Treated as authoritative — most major ATS platforms embed this for
        Google for Jobs indexing, so it's vendor-supplied ground truth rather
        than an inference. Try this before falling back to rendered-text scraping.
        """
        soup = BeautifulSoup(html, "html.parser")
        for script in soup.find_all("script", type="application/ld+json"):
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
            except json.JSONDecodeError:
                continue

            candidates = data.get("@graph", [data]) if isinstance(data, dict) else (
                data if isinstance(data, list) else []
            )
            for candidate in candidates:
                if isinstance(candidate, dict) and candidate.get("@type") == "JobPosting":
                    return candidate
        return None

    def _strip_cookie_boilerplate(self, text: str) -> str:
        text = self._COOKIE_NOTICE_RE.sub(" ", text)          # existing pattern, keep as one option
        text = self._COOKIE_BANNER_TAIL_RE.sub(" ", text)      # new: catches "Decline all Accept all" at the end
        text = self._trim_trailing_cookie_banner(text)         # new: generic fallback heuristic
        return text.strip()

    def _trim_trailing_cookie_banner(self, text: str, window: int = 600) -> str:
        """
        Consent banners are almost always rendered as an overlay, so they show
        up appended at the very end of scraped page text. If any known
        cookie-banner phrase appears within the last `window` chars, cut
        everything from that phrase onward rather than trying to match its
        exact wording (which varies a lot by vendor).
        """
        tail = text[-window:].lower()
        cut_at = None
        for signal in self._COOKIE_TAIL_SIGNALS:
            idx = tail.find(signal)
            if idx != -1:
                candidate = len(text) - window + idx
                cut_at = candidate if cut_at is None else min(cut_at, candidate)
        return text[:cut_at].rstrip() if cut_at is not None else text
        
    def _jobposting_to_fields(self, posting: dict) -> dict:
        """Map a schema.org JobPosting dict onto our extracted-fields shape."""
        extracted = {}

        if desc := posting.get("description"):
            extracted["description"] = Config.strip_html(desc)

        location = posting.get("jobLocation", {})
        address = location.get("address", {}) if isinstance(location, dict) else {}
        if locality := address.get("addressLocality"):
            extracted["location"] = locality

        if posting.get("jobLocationType") == "TELECOMMUTE":
            extracted["is_remote"] = True

        if valid_through := posting.get("validThrough"):
            try:
                from datetime import datetime, timezone
                expiry = datetime.fromisoformat(valid_through.replace("Z", "+00:00"))
                if expiry < datetime.now(timezone.utc):
                    extracted["job_expired"] = True
            except (ValueError, TypeError):
                pass

        base_salary = posting.get("baseSalary", {})
        if isinstance(base_salary, dict):
            value = base_salary.get("value", {})
            if isinstance(value, dict):
                lo, hi = value.get("minValue"), value.get("maxValue")
                if isinstance(lo, (int, float)) or isinstance(hi, (int, float)):
                    extracted["pay_range"] = [lo, hi]

        Config.logger.info(f"Extracted structured JobPosting data: {extracted}")
        return extracted

    async def scrape_apply_url(self, url: str) -> Optional[Union[str, dict]] | ScrapeResult:
        """
        Returns:
          - a dict with job_expired/description/etc if a schema.org JobPosting
            JSON-LD block was found (authoritative — caller should overwrite,
            not merge)
          - a dict {"blocked": True, "status_code": ...} if the site actively
            blocked the request (403/429) — this is NOT evidence the job is
            expired, just that this scrape attempt was refused
          - a str if only rendered text could be scraped (treat as a hint)
          - None on any other failure (timeout, connection error, etc.)
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            Config.logger.warning("Playwright not installed — run: pip install playwright && playwright install chromium")
        else:
            try:
                async with async_playwright() as p:
                    browser = await p.chromium.launch(
                        headless=True,
                        # Reduces (doesn't eliminate) trivial headless-detection
                        # via the navigator.webdriver flag some bot checks look for.
                        args=["--disable-blink-features=AutomationControlled"],
                    )
                    # try/finally guarantees this browser process is closed on
                    # EVERY exit path — including a goto/networkidle timeout —
                    # rather than relying on scattered .close() calls in except
                    # blocks, which are easy to get wrong (e.g. calling .close()
                    # on a browser that was never assigned, or closing one twice).
                    try:
                        context = await browser.new_context(
                            user_agent=self._HEADERS["User-Agent"],
                            viewport={"width": 1280, "height": 800},
                            locale="en-US",
                        )
                        page = await context.new_page()

                        # domcontentloaded, not networkidle, for the initial nav
                        # — networkidle requires zero network activity for
                        # 500ms, which analytics beacons, chat widgets, ad
                        # pixels, or (on sites like ZipRecruiter) a bot-challenge
                        # page's own background polling can prevent indefinitely
                        # even though the actual content already rendered.
                        response = await page.goto(url, timeout=15000, wait_until="domcontentloaded")

                        if response is not None and response.status in self.BLOCKED_STATUS_CODES:
                            Config.logger.warning(
                                f"Blocked (HTTP {response.status}) loading {url} via Playwright"
                            )
                            return {"blocked": True, "status_code": response.status}

                        # Best-effort only: give the page a shorter window to
                        # go idle, but a page that never fully idles is common
                        # and shouldn't discard an otherwise-successful scrape.
                        try:
                            await page.wait_for_load_state("networkidle", timeout=8000)
                        except Exception:
                            Config.logger.debug(
                                f"{url}: networkidle not reached within budget — "
                                "continuing anyway (common with polling/analytics)"
                            )

                        if "myworkdayjobs.com" in url:
                            try:
                                await page.wait_for_selector(
                                    '[data-automation-id="jobPostingDescription"]', timeout=10000
                                )
                            except Exception:
                                Config.logger.warning(
                                    "Workday job description selector never appeared — "
                                    "page may have failed to render or the listing is dead."
                                )

                        if self._is_known_expired_redirect(page.url):
                            Config.logger.warning(f"Known expired redirect detected: {page.url}")
                            return None

                        html = await page.content()
                        jobposting = self._extract_jobposting_jsonld(html)
                        if jobposting:
                            Config.logger.info("Found schema.org JobPosting JSON-LD — using structured data")
                            return self._jobposting_to_fields(jobposting)

                        
                        
                        Config.logger.debug(f"Dumped raw page HTML ({len(html)} chars) to debug_page.html")

                        await page.evaluate(
                            "document.querySelectorAll('nav,footer,header,script,style')"
                            ".forEach(el => el.remove())"
                        )
                        await page.evaluate("""
                            document.querySelectorAll(
                                '[id*="cookie" i], [class*="cookie" i], ' +
                                '[id*="consent" i], [class*="consent" i], ' +
                                '[aria-label*="cookie" i]'
                            ).forEach(el => el.remove())
                        """)
                        new_html = await page.content()
                        
                        texts = []
                        for frame in page.frames:
                            try:
                                frame_text = await frame.inner_text("body")
                                if frame_text:
                                    texts.append(frame_text)
                            except Exception:
                                continue

                        text = max(texts, key=len) if texts else ""
                        Config.logger.info(
                            f"Scraped with Playwright ({len(page.frames)} frame(s) checked) and length={len(text)}"
                        )
                        full_text = self._strip_cookie_boilerplate(text)
                        trimmed = self._trim_to_description(full_text)
                        await asyncio.to_thread(
                                lambda: open("debug_page.html", "w", encoding="utf-8").write(text)
                            )
                        return ScrapeResult(
                                        raw_text=Config.clean_ws(full_text),
                                        trimmed_text=Config.clean_ws(trimmed),
                                    )
                    finally:
                        await browser.close()
            except Exception as e:
                Config.logger.warning(f"Playwright failed: {e} — trying requests fallback")

        try:
            resp = requests.get(url, headers=self._HEADERS, timeout=10)

            if resp.status_code in self.BLOCKED_STATUS_CODES:
                Config.logger.warning(
                    f"Blocked (HTTP {resp.status_code}) requesting {url} — treating as blocked, not expired"
                )
                return {"blocked": True, "status_code": resp.status_code}

            if self._is_known_expired_redirect(resp.url):
                Config.logger.warning(f"Known expired redirect detected for URL: {resp.url}")
                return None

            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            jobposting = self._extract_jobposting_jsonld(resp.text)
            if jobposting:
                Config.logger.info("Found schema.org JobPosting JSON-LD (requests fallback)")
                return self._jobposting_to_fields(jobposting)

            for tag in soup(["nav", "footer", "script", "style", "header"]):
                tag.decompose()
            Config.logger.info("Scraped with requests (static only)")
            full_text = self._strip_cookie_boilerplate(soup.get_text(separator=" "))
            trimmed = self._trim_to_description(full_text)
            return ScrapeResult(
                raw_text=Config.clean_ws(full_text),
                trimmed_text=Config.clean_ws(trimmed),
            )
        except Exception as e:
            Config.logger.warning(f"Requests scrape also failed: {e}")
            return None

    def classify_scraped_text(self, text: str) -> str:
        lowered = text.lower().replace("\u2019", "'").replace("\u2018", "'")
        if any(signal in lowered for signal in self._EXPIRED_SIGNALS):
            return "expired"
        if any(signal in lowered for signal in self._GARBAGE_SIGNALS):
            return "garbage"
        if len(text.strip()) < 300:
            return "garbage"
        return "ok"