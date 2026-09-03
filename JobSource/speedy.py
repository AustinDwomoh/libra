"""
speedy.py - Speedy (speedyapply/2027-SWE-College-Jobs) job source

The README is Markdown with GFM-style pipe tables (no raw HTML <table> tags),
so we convert it to HTML first, then reuse the same BeautifulSoup-based
parsing approach as the Simplify source. Column layout differs from Simplify:

    Simplify: Company(0) | Role(1)     | Location(2) | Application(3) | Age(4)
    Speedy:   Company(0) | Position(1) | Location(2) | Salary(3) | Posting(4) | Age(5)

Speedy also has no continuation-row marker (every row repeats the full
company name), so _update_current_company effectively just returns the
current row's company every time - kept for structural parity with Simplify
and as a safety net if that ever changes.
"""
import asyncio, json, requests, emoji, re, os, math, markdown
from typing import List, Dict, Optional
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from Utils.models import Job
from Utils.constants import JobSource, SpeedyConfig, Defaults, FilePaths, Config
from Utils.run_logging import get_logger, logged_section
from JobSource.base import JobSourceBase
from tqdm import tqdm

logger = get_logger(__name__)


class Speedy(JobSourceBase):
    """Helper class for scraping the Speedy (speedyapply) GitHub README"""

    def __init__(self, url: Optional[str] = None):
        super().__init__()
        self.url = url or SpeedyConfig.DEFAULT_URL
        self.readme_text: Optional[str] = None
        self.jobs_found: int = 0
        self.tables_processed: int = 0
        self.max_age_days: int = self._compute_max_age_days()

    def _compute_max_age_days(self) -> int:
        """
        How far back to look, based on when this last ran successfully.
        No previous run recorded -> fall back to the configured default (full backlog).
        """
        default_max = getattr(SpeedyConfig, "MAX_JOB_AGE_DAYS", 30)
        last_run = self._load_last_run()

        if last_run is None:
            return default_max

        elapsed_days = math.ceil(
            (datetime.now(timezone.utc) - last_run).total_seconds() / 86400
        )
        # never look back further than default_max, but always at least 1 day
        return max(1, min(elapsed_days, default_max))

    def _load_last_run(self) -> Optional[datetime]:
        """Read the timestamp of this source's last successful scrape, if any."""
        path = FilePaths.LAST_RUN
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r") as f:
                data = json.load(f)
            last_run_str = data.get("speedy")
            if last_run_str is None:
                return None
            return datetime.fromisoformat(last_run_str)
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"Speedy: Could not read last run timestamp: {e}")
            return None

    def _save_last_run(self) -> None:
        """Record now as this source's last successful scrape time, preserving other sources' entries."""
        path = FilePaths.LAST_RUN

        data = {}
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
            except json.JSONDecodeError as e:
                logger.warning(f"Speedy: Existing last-run file was corrupt, overwriting: {e}")
                data = {}

        data["speedy"] = datetime.now(timezone.utc).isoformat()

        with open(path, "w") as f:
            json.dump(data, f)

    def fetch_readme(self) -> str:
        """Fetch README (Markdown) content from Speedy GitHub"""
        logger.info(f"Speedy: Fetching README from {self.url}...")
        try:
            resp = self._fetch(self.url)
            self.readme_text = resp.text
            logger.info(f"Speedy: Successfully fetched README ({len(self.readme_text)} characters)")
            return self.readme_text
        except requests.RequestException as e:
            logger.error(f"Speedy: Failed to fetch README: {e}")
            raise

    def _markdown_to_html(self) -> str:
        """Convert the Markdown README's pipe tables into HTML so BeautifulSoup can parse them."""
        if not self.readme_text:
            raise ValueError("README not fetched yet. Call fetch_readme() first.")
        return markdown.markdown(self.readme_text, extensions=["tables"])

    def _clean_company_name(self, name: str) -> str:
        """Clean and normalize company name by removing emojis and extra spaces"""
        no_emoji = emoji.replace_emoji(name, replace='')
        return no_emoji.strip().lower()

    async def parse_tables(self) -> List[Job]:
        """Parse HTML (converted from Markdown) tables to extract job info from Speedy"""
        logger.info("Speedy: Parsing job tables...")

        html = self._markdown_to_html()
        soup = BeautifulSoup(html, "html.parser")
        tables = soup.find_all("table")

        all_jobs = []
        self.tables_processed = 0

        with tqdm(total=len(tables), desc="Speedy Parsing Tables", unit="table", ncols=100) as pbar:
            for table_idx, table in enumerate(tables):
                jobs = await self._parse_single_table(table, table_idx)
                all_jobs.extend(jobs)
                self.tables_processed += 1
                pbar.update(1)

        self.jobs_found = len(all_jobs)
        logger.info(f"Speedy: Parsed {self.jobs_found} valid job entries")

        return all_jobs

    def _extract_date_posted(self, tds) -> Optional[str]:
        """Extract age string from row (Age is the 6th column, index 5)"""
        return tds[5].get_text(strip=True) if len(tds) > 5 else None

    async def _parse_single_table(self, table, table_idx: int) -> List[Job]:
        """Parse a single HTML table"""
        jobs = []
        current_company: Optional[str] = None
        row_count = 0
        stopped_early = False

        for tr in table.find_all("tr"):
            tds = tr.find_all("td")

            if not self._is_valid_row(tds):
                continue

            row_count += 1
            current_company = self._update_current_company(tds, current_company)

            if not current_company:
                continue

            age_str = self._extract_date_posted(tds)
            if self._is_too_old(age_str):
                stopped_early = True
                break  # rows below are all older too - tables are sorted newest-first

            job = await self._map_job(tds, current_company)

            if job.is_valid():
                jobs.append(job)

        logger.debug(
            f"Speedy: Table {table_idx + 1}: "
            f"Processed {row_count} rows, found {len(jobs)} jobs"
            + (" (stopped early - remaining rows too old)" if stopped_early else "")
        )

        return jobs

    def _is_valid_row(self, tds) -> bool:
        """Check if table row has minimum required columns"""
        return bool(tds and len(tds) >= SpeedyConfig.MIN_TABLE_COLUMNS)

    def _update_current_company(
        self,
        tds,
        current_company: Optional[str]
    ) -> Optional[str]:
        """
        Update current company name.
        Speedy has no continuation-row marker (every row repeats the full
        company name), so this just returns the cleaned company name for
        every row. Kept for structural parity with Simplify's parsing flow
        and as a safety net if Speedy ever adds grouped/continuation rows.
        """
        first_col_text = tds[0].get_text(strip=True)

        if first_col_text and first_col_text != getattr(SpeedyConfig, "CONTINUATION_MARKER", None):
            return self._clean_company_name(first_col_text)

        return current_company

    async def _map_job(self, tds, company: str) -> Job:
        """Extract job information from a table row"""
        company_dict = await self._upsert_company(company)

        refined_job = {
            "title": self._extract_title(tds).lower(),
            "location": self._extract_location(tds) or Defaults.LOCATION_NOT_SPECIFIED,
            "is_remote": None,
            "description": "",
            "apply_url": self._extract_link(tds),
            "role_type": "other",  # Speedy doesn't provide role type, so we default to "other"
            "salary_range": self._extract_salary(tds),
            "source": "speedy",
            "tags": [],
        }
        return self._make_job(refined_job, company_dict)

    def _extract_title(self, tds) -> str:
        """Extract job title from row (Position, index 1)"""
        return tds[1].get_text(strip=True) if len(tds) > 1 else ""

    def _extract_location(self, tds) -> str:
        """Extract location from row (index 2)"""
        return tds[2].get_text(strip=True) if len(tds) > 2 else Defaults.UNKNOWN_LOCATION

    def _extract_salary(self, tds) -> Optional[str]:
        """Extract salary from row (index 3) - Speedy provides this, Simplify doesn't"""
        if len(tds) > 3:
            text = tds[3].get_text(strip=True)
            return text if text else None
        return None

    def _extract_link(self, tds) -> Optional[str]:
        """Extract application link from row (Posting column, index 4)"""
        if len(tds) > 4:
            link = self._find_valid_link(tds[4])
            if link:
                return link

        # Fall back to searching all columns
        for td in tds[1:]:  # Skip first column (company name)
            link = self._find_valid_link(td)
            if link:
                return link

        return None

    def _parse_age_to_days(self, age_str: Optional[str]) -> Optional[int]:
        """Convert an age string like '0d', '5d', '2mo', '1yr' into a day count."""
        if not age_str:
            return None
        match = re.match(r"(\d+)\s*(d|mo|yr)", age_str.strip().lower())
        if not match:
            return None
        value, unit = match.groups()
        multiplier = {"d": 1, "mo": 30, "yr": 365}[unit]
        return int(value) * multiplier

    def _is_too_old(self, age_str: Optional[str]) -> bool:
        """True if a job's posted age exceeds the configured max age."""
        days = self._parse_age_to_days(age_str)
        if days is None:
            return False
        return days > self.max_age_days

    def _find_valid_link(self, td) -> Optional[str]:
        """Find a valid link in a table cell"""
        a_tag = td.find("a", href=True)

        if not a_tag:
            return None

        href = a_tag["href"]

        if not href:
            return None

        if self._is_excluded_link(href):
            return None

        return href

    def _is_excluded_link(self, href: str) -> bool:
        """Check if link should be excluded"""
        for prefix in SpeedyConfig.EXCLUDED_LINK_PREFIXES:
            if href.startswith(prefix):
                return True

        for domain in SpeedyConfig.EXCLUDED_LINK_DOMAINS:
            if domain in href:
                return True

        return False

    @logged_section("fetch_jobs")
    async def fetch_jobs(self) -> List[Job]:
        """
        Main method: Fetch and parse jobs from Speedy.
        Returns list of job dictionaries.
        """
        self.fetch_readme()
        jobs = await self.parse_tables()

        logger.info(
            f"Speedy: Completed - {self.tables_processed} tables processed, "
            f"{self.jobs_found} jobs found (max_age_days={self.max_age_days})"
        )

        self._save_last_run()
        return jobs

    def get_stats(self) -> Dict:
        """Get statistics about the scraping operation"""
        return {
            "source": JobSource.SPEEDY.value,
            "tables_processed": self.tables_processed,
            "jobs_found": self.jobs_found,
            "url": self.url
        }


if __name__ == "__main__":
    helper = Speedy()
    jobs = asyncio.run(helper.fetch_jobs())
    jobs = [Job.to_dict(job) for job in jobs]
    with open(FilePaths.SCRAPED_JOBS_JSON, "w") as f:
        json.dump(jobs, f, indent=2)
    stats = helper.get_stats()
    logger.info(f"Speedy: Stats - {stats}")