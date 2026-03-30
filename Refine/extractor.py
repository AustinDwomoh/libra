import re, json, uuid, requests, asyncio
from typing import Optional
from bs4 import BeautifulSoup
from Refine.llm import  GroqProvider, LLMProvider
from Utils.constants import Config
from Utils.models import Job


# ─── Utilities ─────────────────────────────────────────────────────────────────


# ─── Stage 1: Regex ────────────────────────────────────────────────────────────

_PAY_RE = re.compile(
    r"""
    (?P<sym>[€£\$¥₹])?
    (?P<min>[\d][,\d]*(?:\.\d+)?k?)
    \s*(?:[-–—]|to)\s*
    (?P<sym2>[€£\$¥₹])?
    (?P<max>[\d][,\d]*(?:\.\d+)?k?)
    (?:\s*(?:per\s+)?(?:hour|hr|year|yr|annual(?:ly)?|month|mo|week|wk|pa))?
    |
    (?P<sym3>[€£\$¥₹])
    (?P<single>[\d][,\d]*(?:\.\d+)?k?)
    (?:\s*(?:per\s+)?(?:hour|hr|year|yr|annual(?:ly)?|month|mo|week|wk|pa))?
    """,
    re.IGNORECASE | re.VERBOSE,
)

_ROLE_RE = re.compile(
    r"\b(full[\s-]?time|part[\s-]?time|contract(?:or)?|freelance|intern(?:ship)?|temporary)\b",
    re.IGNORECASE,
)
_ROLE_NORM = {
    "fulltime": "full-time", "full time": "full-time",
    "parttime": "part-time", "part time": "part-time",
    "contractor": "contract", "internship": "internship",
    "intern": "internship", "temporary": "contract", "freelance": "freelance",
}

_REMOTE_RE = re.compile(
    r"\b(remote|work from home|wfh|fully remote|remote[\s-]first|anywhere)\b",
    re.IGNORECASE,
)
_ONSITE_RE = re.compile(
    r"\b(on[\s-]?site|in[\s-]?office|in[\s-]?person|hybrid)\b",
    re.IGNORECASE,
)

_EXP_RE = re.compile(
    r"(\d+)\s*(?:to|[-–])\s*(\d+)\s*\+?\s*years?(?:\s+of)?(?:\s+experience)?|"
    r"(\d+)\+\s*years?(?:\s+of)?(?:\s+experience)?|"
    r"(\d+)\s*years?\s+(?:of\s+)?experience",
    re.IGNORECASE,
)



def _regex_pay(text: str) -> Optional[list]:
    """Returns [min, max] or None."""
    for m in _PAY_RE.finditer(text):
        g = m.groupdict()
        try:
            if g.get("min") and g.get("max"):
                lo, hi = Config._norm_amount(g["min"]), Config._norm_amount(g["max"])
                if lo < 10 or hi < 10:
                    continue
                return [lo, hi]
            elif g.get("single"):
                amt = Config._norm_amount(g["single"])
                if amt < 10:
                    continue
                return [amt, None]
        except (ValueError, TypeError):
            continue
    return None

def _regex_remote(text: str) -> Optional[bool]:
    if _REMOTE_RE.search(text):
        return True
    if _ONSITE_RE.search(text):
        return False
    return None


def _regex_role_type(text: str) -> Optional[str]:
    m = _ROLE_RE.search(text)
    if m:
        raw = re.sub(r"[-\s]", "", m.group(0).lower())
        return _ROLE_NORM.get(raw, m.group(0).lower())
    return None


def _regex_experience(text: str) -> Optional[str]:
    m = _EXP_RE.search(text)
    if not m:
        return None
    g = m.groups()
    if g[0] and g[1]:
        return f"{g[0]}-{g[1]}"
    elif g[2]:
        return f"{g[2]}+"
    elif g[3]:
        return g[3]
    return None

def run_regex_stage(job: "Job") -> dict:
    """Run regex over job description. Returns dict of extracted fields."""
    desc = Config.strip_html(job.description or "")
    full_text = f"{job.title or ''} {desc}"
    extracted = {}

    if Config.is_missing(job.pay_range):
        pay = _regex_pay(full_text)
        if pay:
            extracted["pay_range"] = pay

    if Config.is_missing(job.is_remote):
        remote = _regex_remote(full_text)
        if remote is not None:
            extracted["is_remote"] = remote

    if Config.is_missing(job.role_type):
        role = _regex_role_type(full_text)
        if role:
            extracted["role_type"] = role

    if Config.is_missing(job.tags):
        exp = _regex_experience(full_text)
        if exp:
            extracted["tags"] = {"experience_years": exp}

    return extracted


# ─── Scraper ───────────────────────────────────────────────────────────────────

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JobBot/1.0)"}

async def scrape_apply_url(url: str) -> Optional[str]:
    """
    Scrape a URL using Playwright (handles JS-heavy sites: Taleo, Workday, Greenhouse).
    Falls back to plain requests if Playwright is not installed.
    """
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, timeout=15000)
            await page.wait_for_load_state("networkidle", timeout=15000)
            await page.evaluate(
                "document.querySelectorAll('nav,footer,header,script,style')"
                ".forEach(el => el.remove())"
            )
            text = await page.inner_text("body")
            await browser.close()
            Config.logger.info("Scraped with Playwright")
            Config.logger.warning("Playwright scrape is best effort and may fail on some sites. Always verify results.")
            return Config.clean_ws(text)[:10000]

    except ImportError:
        Config.logger.warning("Playwright not installed — run: pip install playwright && playwright install chromium")
    except Exception as e:
        Config.logger.warning(f"Playwright failed: {e} — trying requests fallback")

    try:
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["nav", "footer", "script", "style", "header"]):
            tag.decompose()
        Config.logger.info("Scraped with requests (static only)")
        Config.logger.warning("Requests scrape is a fallback and may miss content on JS-heavy sites.")
        return Config.clean_ws(soup.get_text(separator=" "))[:10000]
    except Exception as e:
        Config.logger.warning(f"Requests scrape also failed: {e}")
        return None


# ─── Apply Extracted Fields to Job ────────────────────────────────────────────

def _apply_to_job(job: "Job", extracted: dict) -> list[str]:
    """
    Write extracted fields onto the Job instance.
    Only fills fields that are currently missing.
    Returns list of field names that were updated.
    """
    filled = []

    for field_name, value in extracted.items():
        if value is None:
            continue

        current = getattr(job, field_name, None)
        if not Config.is_missing(current):
            continue  # never overwrite existing data

        if field_name == "tags":
            if isinstance(value, dict):
                existing = job.tags or {}
                job.tags = {**value, **existing}  # existing keys take priority
                filled.append("tags")
            continue

        setattr(job, field_name, value)
        filled.append(field_name)

    return filled


# ─── Main Entry Point ──────────────────────────────────────────────────────────

async def enrich_job(
    job: "Job",
    provider: Optional[LLMProvider] = None,
    use_llm: bool = True,
) -> dict:
    Config.logger.info(f"Enriching job: {job.title} at {job.company} for {job}")
    if use_llm and provider is None:
        provider = GroqProvider()

    meta = {
        "stages_run": [],
        "fields_filled": [],
        "provider": provider.__class__.__name__ if provider else None,
    }
    fields_to_check = ["pay_range", "is_remote", "role_type", "location", "tags", "description"]

    missing = [f for f in fields_to_check if Config.is_missing(getattr(job, f, None))]
    if not missing:
        Config.logger.info("Job already complete, skipping enrichment")
        return meta

    Config.logger.info(f"Enriching '{job.title}' — missing: {missing}")

    desc_text = Config.strip_html(job.description or "")
    has_description = len(desc_text.strip()) > 100

    # ── Stage 1: Regex on description (only if we have one) ──
    if has_description:
        meta["stages_run"].append("regex")
        extracted = run_regex_stage(job)
        filled = _apply_to_job(job, extracted)
        meta["fields_filled"].extend(f"{f} (regex)" for f in filled)

    # ── Stage 2: LLM ──
    # Run even without a description — use title + apply_url as minimal context.
    # This lets Groq infer role_type, is_remote, and generate a short description.
    missing = [f for f in fields_to_check if Config.is_missing(getattr(job, f, None))]
    if missing and use_llm and provider:
        llm_text = desc_text if has_description else (
            f"Job title: {job.title}\n"
            f"Location: {job.location or 'unknown'}\n"
            f"Apply URL: {job.apply_url or 'unknown'}"
        )
        Config.logger.info(
            f"LLM {'on description' if has_description else 'on title/url'} for: {missing}"
        )
        meta["stages_run"].append("llm_description" if has_description else "llm_title")
        extracted = provider.extract(job, llm_text)
        filled = _apply_to_job(job, extracted)
        meta["fields_filled"].extend(f"{f} (llm)" for f in filled)

    # ── Stage 3: Scrape apply_url ──
    missing = [f for f in fields_to_check if Config.is_missing(getattr(job, f, None))]
    if missing  and job.apply_url:
        Config.logger.info(f"Scraping apply URL for: {missing}")
        meta["stages_run"].append("scrape")
        scraped = await scrape_apply_url(job.apply_url)

        if scraped:
            meta["stages_run"].append("regex_scraped")
            if Config.is_missing(job.pay_range):
                pay = _regex_pay(scraped)
                if pay:
                    job.pay_range = pay
                    meta["fields_filled"].append("pay_range (regex+scrape)")
            if Config.is_missing(job.is_remote):
                remote = _regex_remote(scraped)
                if remote is not None:
                    job.is_remote = remote
                    meta["fields_filled"].append("is_remote (regex+scrape)")
            if Config.is_missing(job.role_type):
                role = _regex_role_type(scraped)
                if role:
                    job.role_type = role
                    meta["fields_filled"].append("role_type (regex+scrape)")

            missing = [f for f in fields_to_check if Config.is_missing(getattr(job, f, None))]
            if missing and use_llm and provider:
                meta["stages_run"].append("llm_scraped")
                extracted = provider.extract(job, scraped)
                filled = _apply_to_job(job, extracted)
                meta["fields_filled"].extend(f"{f} (llm+scrape)" for f in filled)
    Config.logger.info(f"Finished enriching job: {job.title} at {job.company} for {job}")
    Config.logger.info(f"Done. Filled: {meta['fields_filled']}")
    return meta

async def enrich_jobs_batch(
    jobs: list["Job"],
    provider: Optional[LLMProvider] = None,
    use_llm: bool = True,
    llm_delay: float = 0.5,
) -> list[dict]:
    """
    Enrich a list of Job instances in-place.
    Returns list of meta dicts (one per job).
    llm_delay: seconds between LLM calls to respect free tier rate limits.
    """
    if use_llm and provider is None:
        provider = GroqProvider()

    results = []
    for i, job in enumerate(jobs):
        Config.logger.info(f"Job {i+1}/{len(jobs)}")
        meta = await enrich_job(job, provider=provider, use_llm=use_llm)
        results.append(meta)
        if use_llm and i < len(jobs) - 1:
            await asyncio.sleep(llm_delay)
    return results


# ─── Example ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
 
    company_id = uuid.UUID("6c8333ed-7275-4565-9392-81a9aa46aa45")

    job1 = Job(
        title="machine learning intern/co-op",
        company=company_id,
        location="",
        is_remote=False,
        description="",
        apply_url="https://job-boards.greenhouse.io/fspco-op012325/jobs/8427924002?utm_source=Simplify&ref=Simplify",
        role_type="other",
        pay_range=None,
        source="simplify",
        tags={},
    )

    print("=== Before ===")
    print(job1)


    # Swap provider here —  or GeminiProvider()
    meta = asyncio.run(enrich_job(job1, provider=GroqProvider()))

    print("\n=== After ===")
    print(job1)
    print(f"\nmeta: {json.dumps(meta, indent=2)}")