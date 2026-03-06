"""
Job Enricher — fills missing fields on a Job dataclass instance.

Matches the Job dataclass schema exactly:
  - pay_range: [min, max] list (not a dict)
  - is_remote: bool
  - role_type: str
  - location: str
  - tags: dict[str, str]

Pipeline:
  Stage 1 — Regex on description (free, instant)
  Stage 2 — LLM on description (Groq or Gemini)
  Stage 3 — Scrape apply_url with Playwright + LLM (JS-heavy sites like Taleo, Workday, Greenhouse)

Setup:
    pip install groq google-genai beautifulsoup4 requests playwright python-dotenv
    playwright install chromium

    # In your .env file:
    GROQ_API_KEY=your_key_here      # https://console.groq.com  (free, no CC)
    GEMINI_KEY=your_key_here        # https://aistudio.google.com/app/apikey (free tier)
"""

import re, os, json, logging, time, uuid, requests
from abc import ABC, abstractmethod
from dataclasses import dataclass, field as dc_field
from typing import Optional
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)


# ─── Utilities ─────────────────────────────────────────────────────────────────

def strip_html(text: str) -> str:
    return BeautifulSoup(text, "html.parser").get_text(separator=" ").strip()

def clean_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()

def is_missing(value) -> bool:
    """True if a field value should be treated as unfilled."""
    if value is None:
        return True
    if isinstance(value, str) and value.strip() in ("", "Unknown", "other", "unknown"):
        return True
    if isinstance(value, list) and (len(value) == 0 or all(v is None for v in value)):
        return True
    if isinstance(value, dict) and len(value) == 0:
        return True
    return False


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

def _norm_amount(s: str) -> float:
    s = s.replace(",", "").strip()
    return float(s[:-1]) * 1000 if s.lower().endswith("k") else float(s)

def _regex_pay(text: str) -> Optional[list]:
    """Returns [min, max] or None."""
    for m in _PAY_RE.finditer(text):
        g = m.groupdict()
        try:
            if g.get("min") and g.get("max"):
                lo, hi = _norm_amount(g["min"]), _norm_amount(g["max"])
                if lo < 10 or hi < 10:
                    continue
                return [lo, hi]
            elif g.get("single"):
                amt = _norm_amount(g["single"])
                if amt < 10:
                    continue
                return [amt, None]
        except (ValueError, TypeError):
            continue
    return None

_REMOTE_RE = re.compile(
    r"\b(remote|work from home|wfh|fully remote|remote[\s-]first|anywhere)\b",
    re.IGNORECASE,
)
_ONSITE_RE = re.compile(
    r"\b(on[\s-]?site|in[\s-]?office|in[\s-]?person|hybrid)\b",
    re.IGNORECASE,
)

def _regex_remote(text: str) -> Optional[bool]:
    if _REMOTE_RE.search(text):
        return True
    if _ONSITE_RE.search(text):
        return False
    return None

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

def _regex_role_type(text: str) -> Optional[str]:
    m = _ROLE_RE.search(text)
    if m:
        raw = re.sub(r"[-\s]", "", m.group(0).lower())
        return _ROLE_NORM.get(raw, m.group(0).lower())
    return None

_EXP_RE = re.compile(
    r"(\d+)\s*(?:to|[-–])\s*(\d+)\s*\+?\s*years?(?:\s+of)?(?:\s+experience)?|"
    r"(\d+)\+\s*years?(?:\s+of)?(?:\s+experience)?|"
    r"(\d+)\s*years?\s+(?:of\s+)?experience",
    re.IGNORECASE,
)

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

def run_regex_stage(job) -> dict:
    """Run regex over job description. Returns dict of extracted fields."""
    desc = strip_html(job.description or "")
    full_text = f"{job.title or ''} {desc}"
    extracted = {}

    if is_missing(job.pay_range):
        pay = _regex_pay(full_text)
        if pay:
            extracted["pay_range"] = pay

    if is_missing(job.is_remote):
        remote = _regex_remote(full_text)
        if remote is not None:
            extracted["is_remote"] = remote

    if is_missing(job.role_type):
        role = _regex_role_type(full_text)
        if role:
            extracted["role_type"] = role

    if is_missing(job.tags):
        exp = _regex_experience(full_text)
        if exp:
            extracted["tags"] = {"experience_years": exp}

    return extracted


# ─── LLM Prompt (shared) ───────────────────────────────────────────────────────

_LLM_PROMPT = """Extract structured data from this job posting.
Return ONLY valid JSON, no markdown, no explanation.

Schema:
{{
  "title": string or null,
  "location": string or null,
  "is_remote": true | false | null,
  "role_type": "full-time" | "part-time" | "contract" | "internship" | "freelance" | "other" | null,
  "pay_range": [min_number, max_number] or [min_number, null] or null,
  "description": string or null,
  "tags": {{
    "experience_years": string or null,
    "skill_0": string,
    "skill_1": string
    ... up to 10 hard skills as skill_0, skill_1, etc.
  }} or null
}}

Rules:
- pay_range must be a 2-element array: [min, max]. Use null for max if only one value.
  Convert shorthand: 80k -> 80000. Return null if no salary info at all.
- is_remote: true if fully remote, false if on-site or hybrid, null if unclear
- role_type: default "other" if not determinable
- tags: experience_years as "5+" or "3-5", plus top hard/technical skills only
- location: city/country only, null if not mentioned
- description: clean plain-text summary of the role (2-4 sentences). null if not enough info.

Already known (do not override):
{known}

Job posting:
{text}
"""

def _build_prompt(job, text: str) -> str:
    known = {
        "title":     job.title     if not is_missing(job.title)     else None,
        "location":  job.location  if not is_missing(job.location)  else None,
        "is_remote": job.is_remote if not is_missing(job.is_remote) else None,
        "role_type": job.role_type if not is_missing(job.role_type) else None,
        "pay_range": job.pay_range if not is_missing(job.pay_range) else None,
    }
    return _LLM_PROMPT.format(
        known=json.dumps({k: v for k, v in known.items() if v is not None}, indent=2),
        text=text[:4000],
    )

def _normalise_pay(data: dict) -> dict:
    """Ensure pay_range is always [min, max] format."""
    if "pay_range" in data and data["pay_range"] is not None:
        pr = data["pay_range"]
        if isinstance(pr, list) and len(pr) >= 2:
            data["pay_range"] = [pr[0], pr[1]]
        elif isinstance(pr, list) and len(pr) == 1:
            data["pay_range"] = [pr[0], None]
        else:
            data["pay_range"] = None
    return data


# ─── LLM Provider Base Class ───────────────────────────────────────────────────

class LLMProvider(ABC):
    """Base class for LLM providers. Implement `complete(prompt) -> str`."""

    @abstractmethod
    def complete(self, prompt: str) -> str:
        """Send prompt, return raw response text."""
        ...

    def extract(self, job, text: str) -> dict:
        """Build prompt, call LLM, parse and return extracted fields."""
        prompt = _build_prompt(job, text)
        try:
            raw = self.complete(prompt)
            raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
            data = json.loads(raw)
            return _normalise_pay(data)
        except Exception as e:
            log.error(f"[{self.__class__.__name__}] LLM failed: {e}")
            return {}


# ─── Groq Provider ─────────────────────────────────────────────────────────────

class GroqProvider(LLMProvider):
    """
    Groq — recommended default.
    Free tier: 14,400 req/day, no credit card needed.
    Get key: https://console.groq.com

    pip install groq
    GROQ_API_KEY=your_key
    """

    def __init__(self, model: str = "llama-3.3-70b-versatile"):
        self.model = model
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from groq import Groq
            except ImportError:
                raise ImportError("Run: pip install groq")
            api_key = os.getenv("GROQ_API_KEY")
            if not api_key:
                raise ValueError("Set GROQ_API_KEY environment variable")
            self._client = Groq(api_key=api_key)
        return self._client

    def complete(self, prompt: str) -> str:
        client = self._get_client()
        response = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"},  # guarantees valid JSON
        )
        return response.choices[0].message.content


# ─── Gemini Provider ───────────────────────────────────────────────────────────

class GeminiProvider(LLMProvider):
    """
    Google Gemini via google-genai SDK.
    Free tier: 1,500 req/day.
    Get key: https://aistudio.google.com/app/apikey

    pip install google-genai
    GEMINI_KEY=your_key
    """

    def __init__(self, model: str = "gemini-2.5-flash-preview-04-17"):
        self.model = model
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from google import genai
            except ImportError:
                raise ImportError("Run: pip install google-genai")
            api_key = os.getenv("GEMINI_KEY")
            if not api_key:
                raise ValueError("Set GEMINI_KEY environment variable")
            self._client = genai.Client(api_key=api_key)
        return self._client

    def complete(self, prompt: str) -> str:
        client = self._get_client()
        response = client.models.generate_content(
            model=self.model,
            contents=prompt,
        )
        return response.text.strip()


# ─── Scraper ───────────────────────────────────────────────────────────────────

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JobBot/1.0)"}

def scrape_apply_url(url: str) -> Optional[str]:
    """
    Scrape a URL using Playwright (handles JS-heavy sites: Taleo, Workday, Greenhouse).
    Falls back to plain requests if Playwright is not installed.
    """
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=15000)
            page.wait_for_load_state("networkidle", timeout=15000)
            page.evaluate(
                "document.querySelectorAll('nav,footer,header,script,style')"
                ".forEach(el => el.remove())"
            )
            text = page.inner_text("body")
            browser.close()
            log.info("Scraped with Playwright")
            return clean_ws(text)[:5000]

    except ImportError:
        log.warning("Playwright not installed — run: pip install playwright && playwright install chromium")
    except Exception as e:
        log.warning(f"Playwright failed: {e} — trying requests fallback")

    try:
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["nav", "footer", "script", "style", "header"]):
            tag.decompose()
        log.info("Scraped with requests (static only)")
        return clean_ws(soup.get_text(separator=" "))[:5000]
    except Exception as e:
        log.warning(f"Requests scrape also failed: {e}")
        return None


# ─── Apply Extracted Fields to Job ────────────────────────────────────────────

def _apply_to_job(job, extracted: dict) -> list[str]:
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
        if not is_missing(current):
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

def enrich_job(
    job,
    provider: Optional[LLMProvider] = None,
    use_llm: bool = True,
    scrape_if_empty: bool = True,
) -> dict:
    """
    Enrich a Job instance in-place with missing details.

    Args:
        job:             A Job dataclass instance
        provider:        LLMProvider instance (GroqProvider or GeminiProvider).
                         Defaults to GroqProvider if not specified.
        use_llm:         Whether to use LLM as fallback
        scrape_if_empty: Whether to scrape apply_url if description is thin

    Returns:
        meta dict: {"stages_run": [...], "fields_filled": [...]}
    """
    if use_llm and provider is None:
        provider = GroqProvider()  # default to Groq

    meta = {"stages_run": [], "fields_filled": [], "provider": provider.__class__.__name__ if provider else None}
    fields_to_check = ["pay_range", "is_remote", "role_type", "location", "tags", "description"]

    missing = [f for f in fields_to_check if is_missing(getattr(job, f, None))]
    if not missing:
        log.info("Job already complete, skipping enrichment")
        return meta

    log.info(f"Enriching '{job.title}' — missing: {missing}")

    desc_text = strip_html(job.description or "")
    has_description = len(desc_text.strip()) > 100

    # ── Stage 1: Regex on description ──
    if has_description:
        meta["stages_run"].append("regex")
        extracted = run_regex_stage(job)
        filled = _apply_to_job(job, extracted)
        meta["fields_filled"].extend(f"{f} (regex)" for f in filled)

    # ── Stage 2: LLM on description ──
    missing = [f for f in fields_to_check if is_missing(getattr(job, f, None))]
    if missing and use_llm and has_description and provider:
        log.info(f"LLM fallback on description for: {missing}")
        meta["stages_run"].append("llm_description")
        extracted = provider.extract(job, desc_text)
        filled = _apply_to_job(job, extracted)
        meta["fields_filled"].extend(f"{f} (llm)" for f in filled)

    # ── Stage 3: Scrape apply_url + LLM ──
    missing = [f for f in fields_to_check if is_missing(getattr(job, f, None))]
    if missing and scrape_if_empty and job.apply_url:
        log.info(f"Scraping apply URL for: {missing}")
        meta["stages_run"].append("scrape")
        scraped = scrape_apply_url(job.apply_url)

        if scraped and use_llm and provider:
            meta["stages_run"].append("llm_scraped")
            extracted = provider.extract(job, scraped)
            filled = _apply_to_job(job, extracted)
            meta["fields_filled"].extend(f"{f} (llm+scrape)" for f in filled)

    log.info(f"Done. Filled: {meta['fields_filled']}")
    return meta


def enrich_jobs_batch(
    jobs: list,
    provider: Optional[LLMProvider] = None,
    use_llm: bool = True,
    scrape_if_empty: bool = True,
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
        log.info(f"Job {i+1}/{len(jobs)}")
        meta = enrich_job(job, provider=provider, use_llm=use_llm, scrape_if_empty=scrape_if_empty)
        results.append(meta)
        if use_llm and i < len(jobs) - 1:
            time.sleep(llm_delay)
    return results


# ─── Example ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    @dataclass
    class Job:
        title: str
        location: str
        is_remote: bool
        description: str
        company: uuid.UUID = None
        apply_url: Optional[str] = None
        role_type: str = "other"
        pay_range: Optional[list] = None
        source: str = "unknown"
        tags: dict = dc_field(default_factory=dict)

    company_id = uuid.UUID("37615c6d-777a-4cc4-8319-8a2b64fec7c6")

    job1 = Job(
        title="computer science bachelor%27s intern",
        company=company_id,
        location="San Diego, CA",
        is_remote=False,
        description="",
        apply_url="https://kp.taleo.net/careersection/external/jobdetail.ftl?job=1406519&utm_source=Simplify&ref=Simplify",
        role_type="other",
        pay_range=None,
        source="simplify",
        tags={},
    )

    print("=== Before ===")
    print(job1)

    # Swap provider here — GroqProvider() or GeminiProvider()
    meta = enrich_job(job1, provider=GroqProvider(), scrape_if_empty=True)

    print("\n=== After ===")
    print(job1)
    print(f"\nmeta: {json.dumps(meta, indent=2)}")