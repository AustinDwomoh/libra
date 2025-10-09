from typing import List, Dict
import requests
import emoji 
from bs4 import BeautifulSoup
from config import Config

logger = Config.logger
class SimplifyHelper:
    """Helper class for scraping Simplify GitHub README"""
    
    def __init__(self, url: str = None):
        self.url = url or Config.DEFAULT_URL
        self.readme_text = None
    
    def fetch_readme(self):
        """Fetch README content from Simplify GitHub."""
        logger.info(f"Simplify: Fetching README from {self.url}...")
        try:
            resp = requests.get(self.url, timeout=Config.REQUEST_TIMEOUT)
            resp.raise_for_status()
            self.readme_text = resp.text
            logger.info(f"Simplify: Successfully fetched README ({len(self.readme_text)} characters)")
            return self.readme_text
        except requests.Timeout:
            logger.error("Simplify: Request timed out")
            raise
        except requests.RequestException as e:
            logger.error(f"Simplify: Failed to fetch README: {e}")
            raise
    
    def clean_company_name(self, name: str) -> str:
        """Clean and normalize company name by removing emojis and extra spaces."""
        no_emoji = emoji.replace_emoji(name, replace='')
        return no_emoji.strip().lower()
    
    def parse_tables(self) -> List[Dict]:
        """Parse HTML tables to extract job information from Simplify."""
        logger.info("Simplify: Parsing job tables...")
        if not self.readme_text:
            raise ValueError("README not fetched yet. Call fetch_readme() first.")
        
        soup = BeautifulSoup(self.readme_text, "html.parser")
        jobs = []

        tables = soup.find_all("table")
    
        for table_idx, table in enumerate(tables):
            current_company = None
            row_count = 0
            
            for tr in table.find_all("tr"):
                tds = tr.find_all("td")
                if not tds or len(tds) < 3:
                    continue
                
                row_count += 1
                first_col_text = tds[0].get_text(strip=True)
                
                # Check if this is a continuation row (↳) or new company
                if first_col_text and first_col_text != "↳":
                    current_company = first_col_text
                
                if not current_company:
                    continue

                current_company = self.clean_company_name(current_company)
                job = {
                    "company": current_company,
                    "title": tds[1].get_text(strip=True) if len(tds) > 1 else "",
                    "location": tds[2].get_text(strip=True) if len(tds) > 2 else "",
                    "link": None,
                    "source": "simplify"
                }

                # Extract application link
                if len(tds) > 3:
                    a_tag = tds[3].find("a", href=True)
                    if a_tag:
                        href = a_tag["href"]
                        if href and not href.startswith("#") and "github.com" not in href:
                            job["link"] = href
                
                if not job["link"]:
                    for td in tds[1:]:
                        a_tag = td.find("a", href=True)
                        if a_tag:
                            href = a_tag["href"]
                            if href and not href.startswith("#") and "github.com" not in href:
                                job["link"] = href
                                break

          
                if self._is_valid_job(job):
                    jobs.append(job)
            
            logger.debug(f"Simplify: Table {table_idx + 1}: Processed {row_count} rows")

        logger.info(f"Simplify: Parsed {len(jobs)} valid job entries")
        return jobs
    
    def _is_valid_job(self, job):
        """Validate job entry has required fields."""
        is_valid = bool(
            job.get("company") and
            job.get("title") and
            job.get("location") and
            job.get("link")
        )
        return is_valid
    
    def fetch_jobs(self) -> List[Dict]:
        """Main method: Fetch and parse jobs from Simplify."""
        self.fetch_readme()
        return self.parse_tables()
