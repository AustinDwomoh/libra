import re, json, uuid, requests, asyncio
from typing import Optional
from bs4 import BeautifulSoup
from Refine.llm import  LLMProvider, OllamaProvider
from Utils.constants import Config
from Utils.models import Job


# ─── Utilities ─────────────────────────────────────────────────────────────────

# ─── Stage 1: Regex ────────────────────────────────────────────────────────────
class RegexConstants:
    """Constants for regex patterns used in LLM repair and extraction"""
   
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

    # Words that, within a few chars of a number match, indicate it's actually
    # talking about pay rather than e.g. years of experience, headcount, etc.
    _PAY_KEYWORD_RE = re.compile(
        r"\b(salary|compensation|pay|wage|hourly|annual(?:ly)?|stipend|earn|earning|per\s+(?:hour|year|month|week|annum))\b",
        re.IGNORECASE,
    )

    # Words that, if found right next to a number range, signal it's NOT pay
    # (years of experience, headcount, ratings, etc.) — vetoes even when a
    # currency symbol/k-suffix is present in edge cases like "$10-15 years exp".
    _NON_PAY_KEYWORD_RE = re.compile(
        r"\b(years?|yrs?|months?|weeks?|days?|hours?\s+(?:per|a)\s+week|people|employees|reports|stars?|reviews?)\b",
        re.IGNORECASE,
    )

    _PAY_CONTEXT_WINDOW = 25  # chars to look before/after a bare number match for anchor keywords

    
    _EXPIRED_SIGNALS = [s.lower() for s in [
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
        "no longer"
    ]]
    #TODO: add more signals for expired jobs, e.g. "this job is closed", "position has been filled", etc.
    _GARBAGE_SIGNALS = [
        "sign in to apply",
        "log in to continue",
        "please enable javascript",
        "access denied",
        "403 forbidden",
        "404 not found",
        "just a moment",  # cloudflare
        "checking your browser",  # cloudflare
    ]
    _COOKIE_NOTICE_RE = re.compile(
    r"(cookie notice.{0,4000}?accept cookies)",
    re.IGNORECASE | re.DOTALL,
)


    _HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JobBot/1.0)"}

def _has_pay_anchor(match: "re.Match", text: str) -> bool:
    """
    A bare numeric range (no currency symbol, no 'k' suffix, no per-hour/year
    suffix captured in the regex itself) needs extra context before we trust
    it's actually a salary and not e.g. '10-15 years experience'.
    """
    start = max(0, match.start() - RegexConstants._PAY_CONTEXT_WINDOW)
    end = min(len(text), match.end() + RegexConstants._PAY_CONTEXT_WINDOW)
    window = text[start:end]

    if RegexConstants._NON_PAY_KEYWORD_RE.search(window):
        return False
    if RegexConstants._PAY_KEYWORD_RE.search(window):
        return True
    return False


def _time_unit_is_real_word(m: "re.Match", text: str) -> bool:
    """
    _PAY_RE's optional suffix group has no trailing \\b, so against text like
    "10-15 years experience" it can match just "year" out of "years" — and a
    boundary check against the truncated match group alone would wrongly see
    end-of-string as a word boundary. Check the real next character in the
    full source text instead: if it's a word char (the "s" in "years"), the
    "time unit" was actually just a prefix of a longer word, not a real anchor.
    """
    if m.end() >= len(text):
        return True
    return not text[m.end()].isalnum()



def _strip_cookie_boilerplate(text: str) -> str:
    """Remove cookie/consent notice blocks that DOM-based removal missed
    (most consent widgets render in Shadow DOM, which page.evaluate's
    querySelectorAll can't see)."""
    return RegexConstants._COOKIE_NOTICE_RE.sub(" ", text)

def _regex_pay(text: str) -> Optional[list]:
    """Returns [min, max] or None."""
    for m in RegexConstants._PAY_RE.finditer(text):
        g = m.groupdict()

        # Does this match carry its own anchor (currency symbol, 'k' suffix,
        # or a captured time-unit like 'hour'/'year')? If not, it's a bare
        # number range and needs a nearby pay keyword to be trusted.
        has_symbol = bool(g.get("sym") or g.get("sym2") or g.get("sym3"))
        has_k_suffix = any(
            (g.get(key) or "").lower().endswith("k")
            for key in ("min", "max", "single")
        )
        matched_time_unit = re.search(
            r"(?:per\s+)?(?:hour|hr|year|yr|annual(?:ly)?|month|mo|week|wk|pa)\s*$",
            m.group(0), re.IGNORECASE,
        )
        has_time_unit = bool(matched_time_unit) and _time_unit_is_real_word(m, text)

        if not (has_symbol or has_k_suffix or has_time_unit):
            if not _has_pay_anchor(m, text):
                continue

        try:
            if g.get("min") and g.get("max"):
                min_raw, max_raw = g["min"], g["max"]
                # Shorthand like "90-110k": k-suffix often only appears on the
                # second number but applies to both. Propagate it to min.
                if max_raw.lower().endswith("k") and not min_raw.lower().endswith("k"):
                    min_raw = f"{min_raw}k"
                lo, hi = Config._norm_amount(min_raw), Config._norm_amount(max_raw)
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
    if RegexConstants._REMOTE_RE.search(text):
        return True
    if RegexConstants._ONSITE_RE.search(text):
        return False
    return None


def _regex_role_type(text: str) -> Optional[str]:
    m = RegexConstants._ROLE_RE.search(text)
    if m:
        raw = re.sub(r"[-\s]", "", m.group(0).lower())
        return RegexConstants._ROLE_NORM.get(raw, m.group(0).lower())
    return None


def _regex_experience(text: str) -> Optional[str]:
    m = RegexConstants._EXP_RE.search(text)
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
def _extract_jobposting_jsonld(html: str) -> Optional[dict]:
    """
    Look for a schema.org JobPosting JSON-LD block in the page source.
    Most major ATS platforms (Workday, Greenhouse, Lever, etc.) embed this
    for Google for Jobs indexing — it's structured, complete, and avoids
    every scraping headache (Shadow DOM cookie banners, iframes, collapsed
    'show more' sections) entirely. Try this before falling back to
    rendered-text scraping.
    """
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", type="application/ld+json"):
        if not script.string:
            continue
        try:
            data = json.loads(script.string)
        except json.JSONDecodeError:
            continue

        # Sometimes wrapped in a @graph array of multiple structured-data blocks
        candidates = data.get("@graph", [data]) if isinstance(data, dict) else (
            data if isinstance(data, list) else []
        )
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate.get("@type") == "JobPosting":
                return candidate
    return None


def _jobposting_to_fields(posting: dict) -> dict:
    """Map a schema.org JobPosting dict onto our extracted-fields shape."""
    extracted = {}

    if desc := posting.get("description"):
        # JobPosting descriptions are often HTML-encoded; strip tags/entities
        extracted["description"] = Config.strip_html(desc)[:1000]

    location = posting.get("jobLocation", {})
    address = location.get("address", {}) if isinstance(location, dict) else {}
    locality = address.get("addressLocality")
    if locality:
        extracted["location"] = locality

    if posting.get("jobLocationType") == "TELECOMMUTE":
        extracted["is_remote"] = True

    # validThrough is the cleanest possible expiry signal when present —
    # an explicit date beats text-matching "this job has expired" phrases.
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

    return extracted

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

            # Workday-specific: the job description has a stable data-automation-id
            # regardless of tenant styling. Wait for it explicitly rather than
            # trusting networkidle, which can fire before client-side rendering
            # actually finishes painting the content.
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

           
           
            html = await page.content()
            await asyncio.to_thread(
                    lambda: open("debug_page.html", "w", encoding="utf-8").write(html)
                )
            Config.logger.debug(f"Dumped raw page HTML ({len(html)} chars) to debug_page.html")

            await page.evaluate(
                "document.querySelectorAll('nav,footer,header,script,style')"
                ".forEach(el => el.remove())"
            )
            # Strip cookie/consent banners — these rarely live in semantic tags, so target
            # common attribute/class patterns instead.
            await page.evaluate("""
                        document.querySelectorAll(
                '[id*="cookie" i], [class*="cookie" i], ' +
                '[id*="consent" i], [class*="consent" i], ' +
                '[aria-label*="cookie" i]'
            ).forEach(el => el.remove())
        """)
            texts = []
            for frame in page.frames:
                try:
                    frame_text = await frame.inner_text("body")
                    if frame_text:
                        texts.append(frame_text)
                except Exception:
                    continue

            text = max(texts, key=len) if texts else ""
            
            await browser.close()
            Config.logger.info(
                f"Scraped with Playwright ({len(page.frames)} frame(s) checked) and length={len(text)}"
            )
            Config.logger.warning("Playwright scrape is best effort and may fail on some sites. Always verify results.")
            text = _strip_cookie_boilerplate(text)
            return Config.clean_ws(text)[:10000]

    except ImportError:
        Config.logger.warning("Playwright not installed — run: pip install playwright && playwright install chromium")
    except Exception as e:
        Config.logger.warning(f"Playwright failed: {e} — trying requests fallback")

    try:
        resp = requests.get(url, headers=RegexConstants._HEADERS, timeout=10)
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
    
def classify_scraped_text(text: str) -> str:
    lowered = text.lower().replace("\u2019", "'").replace("\u2018", "'")

    if any(signal in lowered for signal in RegexConstants._EXPIRED_SIGNALS):
        return "expired"

    if any(signal in lowered for signal in RegexConstants._GARBAGE_SIGNALS):
        return "garbage"

    if len(text.strip()) < 300:
        return "garbage"

    return "ok"

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

def _mark_expired(job: "Job", meta: dict) -> dict:
    """Shared exit path for any stage that determines the listing is expired."""
    job.description = "This listing is no longer available."
    meta["expired"] = True
    Config.logger.info(f"Finished enriching job: {job.title} at {job.company} for {job}")
    Config.logger.info(f"Done. Filled: {meta['fields_filled']}")
    return meta


async def enrich_job(
    job: "Job",
    provider: Optional[LLMProvider] = None,
    use_llm: bool = True,
) -> dict:
    Config.logger.info(f"Enriching job: {job.title} at {job.company} for {job}")
    if use_llm and provider is None:
        provider = OllamaProvider()

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

    # ── Stage 2: Scrape apply_url ──
    missing = [f for f in fields_to_check if Config.is_missing(getattr(job, f, None))]
    if missing and job.apply_url:
        Config.logger.info(f"Scraping apply URL for: {missing}")
        meta["stages_run"].append("scrape")
        scraped = await scrape_apply_url(job.apply_url)
        Config.logger.info(f"Scraped text length: {len(scraped) if scraped else 0}")
        Config.logger.debug(f"Scraped text: {scraped[:500] if scraped else 'None'}")

        if scraped is not None:
            scrape_status = classify_scraped_text(scraped or "")

            if scrape_status == "expired":
                Config.logger.warning(f"Listing expired: {job.title} @ {job.apply_url}")
                meta["stages_run"].append("scrape_expired")
                return _mark_expired(job, meta)

            elif scrape_status == "garbage":
                Config.logger.warning(f"Scraped garbage for: {job.title} — skipping LLM on scraped text")
                meta["stages_run"].append("scrape_garbage")

            else:
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
                    if extracted.get("job_expired"):
                        meta["stages_run"].append("llm_expired")
                        return _mark_expired(job, meta)
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
        provider = OllamaProvider()

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
        title="Associate Web Developer (.Net)",
        company=company_id,
        location="",
        is_remote=False,
        description="",
        apply_url="https://job-boards.greenhouse.io/logicgate/jobs/4671118005?utm_source=Simplify&ref=Simplify",
        role_type="other",
        pay_range=None,
        source="simplify",
        tags={},
    )

    print("=== Before ===")
    print(job1)


    # Swap provider here —  or GeminiProvider()
    meta = asyncio.run(enrich_job(job1, provider=OllamaProvider()))

    print("\n=== After ===")
    print(job1)
    print(f"\nmeta: {json.dumps(meta, indent=2)}") 
    #print(asyncio.run(scrape_apply_url("https://generac.wd5.myworkdayjobs.com/en-US/external/job/Waukesha-WI---USA/Intern-IT---Application-Development--Data-Integration_JR12491?utm_source=Simplify&ref=Simplify")))
    #print(asyncio.run(scrape_apply_url("https://tencent.wd1.myworkdayjobs.com/Tencent_Careers/job/US-California-Palo-Alto/Hunyuan-Multimodal-Algorithm-Researcher-Intern-Omni-Modal---_R107051?ref=Simplify")))