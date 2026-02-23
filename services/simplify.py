"""
simplify.py - Refactored with constants and improved structure
"""
from typing import List, Dict, Optional
import requests
import emoji
from bs4 import BeautifulSoup
from services.config import Config
from services.constants import (
    JobSource,
    SimplifyConfig,
    HTTPStatus,
    Defaults
)

logger = Config.logger


class SimplifyHelper:
    """Helper class for scraping Simplify GitHub README"""
    
    def __init__(self, url: Optional[str] = None):
        self.url = url or Config.DEFAULT_URL
        self.readme_text: Optional[str] = None
        self.jobs_found: int = 0
        self.tables_processed: int = 0
    
    def fetch_readme(self) -> str:
        """Fetch README content from Simplify GitHub"""
        logger.info(f"Simplify: Fetching README from {self.url}...")
        
        try:
            resp = requests.get(self.url, timeout=Config.REQUEST_TIMEOUT)
            resp.raise_for_status()
            
            self.readme_text = resp.text
            logger.info(
                f"Simplify: Successfully fetched README "
                f"({len(self.readme_text)} characters)"
            )
            return self.readme_text
            
        except requests.Timeout:
            logger.error("Simplify: Request timed out")
            raise
        except requests.RequestException as e:
            logger.error(f"Simplify: Failed to fetch README: {e}")
            raise
    
    def clean_company_name(self, name: str) -> str:
        """Clean and normalize company name by removing emojis and extra spaces"""
        no_emoji = emoji.replace_emoji(name, replace='')
        return no_emoji.strip().lower()
    
    def parse_tables(self) -> List[Dict]:
        """Parse HTML tables to extract job information from Simplify"""
        logger.info("Simplify: Parsing job tables...")
        
        if not self.readme_text:
            raise ValueError("README not fetched yet. Call fetch_readme() first.")
        
        soup = BeautifulSoup(self.readme_text, "html.parser")
        tables = soup.find_all("table")
        
        all_jobs = []
        self.tables_processed = 0
        
        for table_idx, table in enumerate(tables):
            jobs = self._parse_single_table(table, table_idx)
            all_jobs.extend(jobs)
            self.tables_processed += 1
        
        self.jobs_found = len(all_jobs)
        logger.info(f"Simplify: Parsed {self.jobs_found} valid job entries")
        
        return all_jobs
    
    def _parse_single_table(self, table, table_idx: int) -> List[Dict]:
        """Parse a single HTML table"""
        jobs = []
        current_company: Optional[str] = None
        row_count = 0
        
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            
            if not self._is_valid_row(tds):
                continue
            
            row_count += 1
            current_company = self._update_current_company(tds, current_company)
            
            if not current_company:
                continue
            
            job = self._extract_job_from_row(tds, current_company)
            
            if self._is_valid_job(job):
                jobs.append(job)
        
        logger.debug(
            f"Simplify: Table {table_idx + 1}: "
            f"Processed {row_count} rows, found {len(jobs)} jobs"
        )
        
        return jobs
    
    def _is_valid_row(self, tds) -> bool:
        """Check if table row has minimum required columns"""
        return bool(tds and len(tds) >= SimplifyConfig.MIN_TABLE_COLUMNS)
    
    def _update_current_company(
        self, 
        tds, 
        current_company: Optional[str]
    ) -> Optional[str]:
        """
        Update current company name.
        Returns new company name or keeps current if it's a continuation row.
        """
        first_col_text = tds[0].get_text(strip=True)
        
        # Check if this is a continuation row
        if first_col_text and first_col_text != SimplifyConfig.CONTINUATION_MARKER:
            return self.clean_company_name(first_col_text)
        
        return current_company
    
    def _extract_job_from_row(self, tds, company: str) -> Dict:
        """Extract job information from a table row"""
        job = {
            "company": company,
            "title": self._extract_title(tds),
            "location": self._extract_location(tds),
            "link": self._extract_link(tds),
            "source": JobSource.SIMPLIFY.value
        }
        
        return job
    
    def _extract_title(self, tds) -> str:
        """Extract job title from row"""
        return tds[1].get_text(strip=True) if len(tds) > 1 else ""
    
    def _extract_location(self, tds) -> str:
        """Extract location from row"""
        return tds[2].get_text(strip=True) if len(tds) > 2 else Defaults.UNKNOWN_LOCATION
    
    def _extract_link(self, tds) -> Optional[str]:
        """Extract application link from row"""
        # First try the 4th column (standard application link column)
        if len(tds) > 3:
            link = self._find_valid_link(tds[3])
            if link:
                return link
        
        # Fall back to searching all columns
        for td in tds[1:]:  # Skip first column (company name)
            link = self._find_valid_link(td)
            if link:
                return link
        
        return None
    
    def _find_valid_link(self, td) -> Optional[str]:
        """Find a valid link in a table cell"""
        a_tag = td.find("a", href=True)
        
        if not a_tag:
            return None
        
        href = a_tag["href"]
        
        if not href:
            return None
        
        # Filter out invalid links
        if self._is_excluded_link(href):
            return None
        
        return href
    
    def _is_excluded_link(self, href: str) -> bool:
        """Check if link should be excluded"""
        # Check prefixes
        for prefix in SimplifyConfig.EXCLUDED_LINK_PREFIXES:
            if href.startswith(prefix):
                return True
        
        # Check domains
        for domain in SimplifyConfig.EXCLUDED_LINK_DOMAINS:
            if domain in href:
                return True
        
        return False
    
    def _is_valid_job(self, job: Dict) -> bool:
        """Validate job entry has all required fields"""
        required_fields = ["company", "title", "location", "link"]
        
        for field in required_fields:
            if not job.get(field):
                return False
        
        return True
    
    def fetch_jobs(self) -> List[Dict]:
        """
        Main method: Fetch and parse jobs from Simplify.
        Returns list of job dictionaries.
        """
        self.fetch_readme()
        jobs = self.parse_tables()
        
        logger.info(
            f"Simplify: Completed - {self.tables_processed} tables processed, "
            f"{self.jobs_found} jobs found"
        )
        
        return jobs
    
    def get_stats(self) -> Dict:
        """Get statistics about the scraping operation"""
        return {
            "source": JobSource.SIMPLIFY.value,
            "tables_processed": self.tables_processed,
            "jobs_found": self.jobs_found,
            "url": self.url
        }


# Utility functions
def clean_company_name(name: str) -> str:
    """Standalone utility to clean company names"""
    no_emoji = emoji.replace_emoji(name, replace='')
    return no_emoji.strip().lower()


if __name__ == "__main__":
    helper = SimplifyHelper()
    jobs = helper.fetch_jobs()
    with open("simplify.json", "w") as f:
        import json
        json.dump(jobs, f, indent=2)
    stats = helper.get_stats()
    logger.info(f"Simplify: Stats - {stats}")