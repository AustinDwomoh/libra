from bs4 import BeautifulSoup
from typing import Optional

from Utils.constants import Config
import json, requests, asyncio, re
from typing import Optional, Union
from bs4 import BeautifulSoup
import json, requests, asyncio, re


class Pirate:
    def __init__(self):
        self._COOKIE_NOTICE_RE = re.compile(
            r"(cookie notice.{0,4000}?accept cookies)",
            re.IGNORECASE | re.DOTALL,
        )

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
            "access denied",
            "403 forbidden",
            "404 not found",
            "just a moment",  # cloudflare
            "checking your browser",  # cloudflare
            # Removed bare "sign in" / "log in" — these appear in legitimate
            # job descriptions for any auth/identity-related role.
        ]

        self._SITE_EXPIRED_URL_PATTERNS = {
            "linkedin.com": [r"trk=expired_jd_redirect", r"/jobs/[\w-]+-jobs\?"],
            "myworkdayjobs.com": [r"/error", r"/notfound", r"sessionTimedOut"],
        }

        self._HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JobBot/1.0)"}

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
        return self._COOKIE_NOTICE_RE.sub(" ", text)

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

    async def scrape_apply_url(self, url: str) -> Optional[Union[str, dict]]:
        """
        Returns a dict if a schema.org JobPosting JSON-LD block was found
        (authoritative, vendor-supplied — caller should overwrite, not merge),
        a str if only rendered text could be scraped (treat as a hint —
        caller should fill gaps via regex/LLM as before), or None on failure.
        """
        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(url, timeout=15000)
                await page.wait_for_load_state("networkidle", timeout=15000)

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
                    await browser.close()
                    return None

                html = await page.content()
                jobposting = self._extract_jobposting_jsonld(html)
                if jobposting:
                    Config.logger.info("Found schema.org JobPosting JSON-LD — using structured data")
                    await browser.close()  # was leaking on this path
                    return self._jobposting_to_fields(jobposting)

                if getattr(Config, "DEBUG_SCRAPE", False):
                    await asyncio.to_thread(
                        lambda: open("debug_page.html", "w", encoding="utf-8").write(html)
                    )
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
                text = self._strip_cookie_boilerplate(text)
                return Config.clean_ws(text)[:10000]

        except ImportError:
            Config.logger.warning("Playwright not installed — run: pip install playwright && playwright install chromium")
        except Exception as e:
            Config.logger.warning(f"Playwright failed: {e} — trying requests fallback")

        try:
            resp = requests.get(url, headers=self._HEADERS, timeout=10)
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
            text = self._strip_cookie_boilerplate(soup.get_text(separator=" "))
            return Config.clean_ws(text)[:10000]
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