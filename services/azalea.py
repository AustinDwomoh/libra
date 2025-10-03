import requests, emoji,logging,json,ta
from bs4 import BeautifulSoup
from assist import SponsorshipDB
from db_manager import JobDatabase

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class Config:
    """Configuration constants for the scraper."""
    DEFAULT_URL = "https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/README.md"
    SPONSORSHIP_CSV = "resources/Employer_info.csv"
    FUZZY_THRESHOLD = 90
    REQUEST_TIMEOUT = 10


class Azalea_:
    """Web scraper for job listings with sponsorship tagging."""
    
    def __init__(self, url=None):
        self.url = url or Config.DEFAULT_URL
        self.readme_text = None
        self.jobs = []

    def fetch_readme(self):
        """Fetch README content from URL."""
        logger.info(f"Fetching README from {self.url}...")
        try:
            resp = requests.get(self.url, timeout=Config.REQUEST_TIMEOUT)
            resp.raise_for_status()
            self.readme_text = resp.text
            logger.info(f"Successfully fetched README ({len(self.readme_text)} characters)")
            return self.readme_text
        except requests.Timeout:
            logger.error("Request timed out")
            raise
        except requests.RequestException as e:
            logger.error(f"Failed to fetch README: {e}")
            raise

    def clean_company_name(self, name: str) -> str:
        """Clean and normalize company name by removing emojis and extra spaces."""
        no_emoji = emoji.replace_emoji(name, replace='')
        return no_emoji.strip().lower()
    def parse_tables(self):
        """Parse HTML tables to extract job information."""
        logger.info("Parsing job tables...")
        if not self.readme_text:
            raise ValueError("README not fetched yet. Call fetch_readme() first.")
        
        soup = BeautifulSoup(self.readme_text, "html.parser")
        jobs = []

        tables = soup.find_all("table")
        logger.info(f"Found {len(tables)} tables to parse")

        for table_idx, table in enumerate(tables):
            current_company = None
            row_count = 0
            
            for tr in table.find_all("tr"):
                tds = tr.find_all("td")
                if not tds or len(tds) < 3:  # Skip if not enough columns
                    continue
                
                row_count += 1
                first_col_text = tds[0].get_text(strip=True)
                
                # Check if this is a continuation row (↳) or new company
                if first_col_text and first_col_text != "↳":
                    current_company = first_col_text
                
                if not current_company:
                    continue

                # Extract job information
                current_company = self.clean_company_name(current_company)
                job = {
                    "company": current_company,
                    "title": tds[1].get_text(strip=True) if len(tds) > 1 else "",
                    "location": tds[2].get_text(strip=True) if len(tds) > 2 else "",
                    "link": None
                }

                # Extract application link - try column 3 first
                if len(tds) > 3:
                    a_tag = tds[3].find("a", href=True)
                    if a_tag:
                        href = a_tag["href"]
                        if href and not href.startswith("#") and "github.com" not in href:
                            job["link"] = href
                
                # Fallback: search other cells if no link found yet
                if not job["link"]:
                    for td in tds[1:]:  # Skip first column (company name)
                        a_tag = td.find("a", href=True)
                        if a_tag:
                            href = a_tag["href"]
                            if href and not href.startswith("#") and "github.com" not in href:
                                job["link"] = href
                                break

                # Validate and add job
                if self._is_valid_job(job):
                    jobs.append(job)
            
            logger.debug(f"Table {table_idx + 1}: Processed {row_count} rows")

        self.jobs = jobs
        logger.info(f"Parsed {len(jobs)} valid job entries")
        return jobs

    def _is_valid_job(self, job):
        """Validate job entry has required fields."""
        is_valid = bool(
            job.get("company") and
            job.get("title") and
            job.get("location") and
            job.get("link")
        )

        if not is_valid:
            logger.debug(f"Invalid job entry: {job}")

        return is_valid
    
    def tag_sponsorship(self, sponsorship_db, use_fuzzy, threshold=None):
        """Tag jobs with sponsorship information."""
        threshold = threshold or Config.FUZZY_THRESHOLD
        
        if not self.jobs:
            logger.warning("No jobs to tag. Parsing tables first...")
            self.parse_tables()

        logger.info(f"Tagging {len(self.jobs)} jobs with sponsorship info...")
        tagged_count = 0

        for job in self.jobs:
            company = job.get("company")
            
            if use_fuzzy:
                has_sponsorship = sponsorship_db.fuzzy_match(company, threshold)
            else:
                has_sponsorship = sponsorship_db.has_sponsorship(company)
            
            job["sponsorship"] = "Likely sponsorship" if has_sponsorship else "No record found"
            
            if has_sponsorship:
                tagged_count += 1
        
        logger.info(f"Sponsorship tagging complete: {tagged_count}/{len(self.jobs)} with likely sponsorship")

    def run(self, use_fuzzy=True):
        """
        Main execution method.
        
        Args:
            use_fuzzy: Whether to use fuzzy matching for sponsorship
            clear_existing: If True, deletes all existing jobs before inserting
            use_upsert: If True, use upsert instead of insert (requires unique constraint)
        
        Returns:
            Dictionary with execution statistics
        """
        stats = {
            'fetched': 0,
            'parsed': 0,
            'inserted': 0,
            'updated': 0,
            'errors': 0
        }
        
        try:
            # Step 1: Fetch and parse data
            self.fetch_readme()
            stats['fetched'] = 1
            
            self.parse_tables()
            stats['parsed'] = len(self.jobs)
            
            if not self.jobs:
                logger.warning("No jobs found to process")
                return stats
            
            # Step 2: Tag with sponsorship info
            logger.info("Loading sponsorship database...")
            try:
                sponsorship_db = SponsorshipDB(csv_paths=[Config.SPONSORSHIP_CSV])
                self.tag_sponsorship(sponsorship_db, use_fuzzy=use_fuzzy)
            except Exception as e:
                logger.warning(f"Could not load sponsorship database: {e}")
                logger.info("Continuing without sponsorship tagging...")
            
            # Step 3: Save jobs to JSON for cross-checking
            json_path = "resources/scraped_jobs.json"
            try:
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(self.jobs, f, indent=2, ensure_ascii=False)
                logger.info(f"Saved {len(self.jobs)} jobs to {json_path}")
            except Exception as e:
                logger.warning(f"Could not save jobs to JSON: {e}")

            # Step 4: Insert into database using context manager
            with JobDatabase() as jb_db:
                inserted = jb_db.insert_jobs_bulk(self.jobs)
                stats['inserted'] = inserted
                total_jobs = jb_db.count_jobs()
                logger.info(f"Database now contains {total_jobs} total jobs")

                # Get sponsorship breakdown
                sponsored_jobs = jb_db.get_jobs_with_sponsorship("Likely sponsorship")
            
            logger.info("=" * 60)
            logger.info("EXECUTION SUMMARY")
            logger.info(f"Parsed: {stats['parsed']} jobs")
            logger.info(f"Inserted: {stats['inserted']} jobs")
            logger.info(f"Jobs with likely sponsorship: {len(sponsored_jobs)}")
            logger.info("=" * 60)
            
            return stats
            
        except Exception as e:
            stats['errors'] = 1
            logger.error(f"Error in run process: {e}", exc_info=True)
            raise


if __name__ == "__main__":
    scraper = Azalea_()
    scraper.run(use_fuzzy=True)