import requests, emoji, logging, json, os, time
from bs4 import BeautifulSoup
from assist import SponsorshipDB
from db_manager import JobDatabase
from typing import List, Dict
from dotenv import load_dotenv

load_dotenv()

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
    JSEARCH_API_URL = "https://jsearch.p.rapidapi.com/search"
    REMOTEOK_API_URL = "https://remoteok.com/api"


# ============================================================================
# HELPER CLASSES - Job Source Scrapers
# ============================================================================

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
        logger.info(f"Simplify: Found {len(tables)} tables to parse")

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

                # Extract job information
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
                
                # Fallback: search other cells
                if not job["link"]:
                    for td in tds[1:]:
                        a_tag = td.find("a", href=True)
                        if a_tag:
                            href = a_tag["href"]
                            if href and not href.startswith("#") and "github.com" not in href:
                                job["link"] = href
                                break

                # Validate and add job
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

        if not is_valid:
            logger.debug(f"Simplify: Invalid job entry: {job}")

        return is_valid
    
    def fetch_jobs(self) -> List[Dict]:
        """Main method: Fetch and parse jobs from Simplify."""
        self.fetch_readme()
        return self.parse_tables()


class JSearchHelper:
    """Helper class for JSearch API integration"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            "X-RapidAPI-Key": api_key,
            "X-RapidAPI-Host": "jsearch.p.rapidapi.com"
        }
    
    def fetch_internships(self, query: str = "software intern", page: int = 1) -> List[Dict]:
        """Fetch internships from JSearch API"""
        logger.info(f"JSearch: Fetching results for '{query}'")
        
        params = {
            "query": query,
            "page": str(page),
            "num_pages": "1",
            "date_posted": "all",
            "employment_types": "INTERN"
        }
        
        try:
            response = requests.get(
                Config.JSEARCH_API_URL,
                headers=self.headers,
                params=params,
                timeout=Config.REQUEST_TIMEOUT
            )
            response.raise_for_status()
            
            data = response.json()
            jobs = data.get("data", [])
            
            logger.info(f"JSearch: Found {len(jobs)} jobs for '{query}'")
            return [self._map_job(job) for job in jobs]
            
        except requests.RequestException as e:
            logger.error(f"JSearch API error: {e}")
            return []
    
    def _map_job(self, job: Dict) -> Dict:
        """Map JSearch response to standard job format"""
        return {
            "company": job.get("employer_name", ""),
            "title": job.get("job_title", ""),
            "location": self._get_location(job),
            "link": job.get("job_apply_link", ""),
            "source": "jsearch",
            "date_posted": job.get("job_posted_at_datetime_utc"),
            "description": job.get("job_description"),
            "remote": job.get("job_is_remote", False),
            "sponsorship": None
        }
    
    def _get_location(self, job: Dict) -> str:
        """Extract location from JSearch job"""
        city = job.get("job_city", "")
        state = job.get("job_state", "")
        country = job.get("job_country", "")
        
        parts = [p for p in [city, state, country] if p]
        return ", ".join(parts) if parts else "Not specified"
    
    def fetch_jobs(self, queries: List[str] = None) -> List[Dict]:
        """Main method: Fetch jobs for multiple search queries with rate limiting"""
        default_queries = [
            "software engineer intern",
            "data analyst intern",
            "frontend developer intern",
            "web developer intern"
        ]
        
        queries = queries or default_queries
        all_jobs = []
        
        for query in queries:
            jobs = self.fetch_internships(query)
            all_jobs.extend(jobs)
            time.sleep(1)  # Rate limiting between queries
        
        logger.info(f"JSearch: Total {len(all_jobs)} jobs fetched")
        return all_jobs


class RemoteOKHelper:
    """Helper class for RemoteOK API integration"""
    
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
    
    def fetch_jobs(self) -> List[Dict]:
        """Main method: Fetch jobs from RemoteOK API"""
        logger.info("RemoteOK: Fetching jobs...")
        
        try:
            response = requests.get(
                Config.REMOTEOK_API_URL,
                headers=self.headers,
                timeout=Config.REQUEST_TIMEOUT
            )
            response.raise_for_status()
            
            jobs = response.json()[1:]  # Skip metadata at index 0
            
            # Filter for internships and relevant roles
            internship_jobs = [
                self._map_job(job) for job in jobs
                if self._is_relevant_job(job)
            ]
            
            logger.info(f"RemoteOK: Found {len(internship_jobs)} relevant jobs")
            return internship_jobs
            
        except requests.RequestException as e:
            logger.error(f"RemoteOK API error: {e}")
            return []
    
    def _is_relevant_job(self, job: Dict) -> bool:
        """Check if job is relevant (internship or entry-level tech role)"""
        position = job.get("position", "").lower()
        tags = [t.lower() for t in job.get("tags", [])]
        
        # Look for internships
        internship_keywords = ["intern", "internship"]
        is_internship = any(kw in position for kw in internship_keywords)
        
        # Or relevant tech roles with intern tag
        relevant_keywords = ["frontend", "backend", "fullstack", "data", "software", "web", "developer", "engineer"]
        is_relevant_tech = any(kw in position or kw in tags for kw in relevant_keywords)
        has_intern_tag = any(kw in tags for kw in internship_keywords)
        
        return is_internship or (is_relevant_tech and has_intern_tag)
    
    def _map_job(self, job: Dict) -> Dict:
        """Map RemoteOK response to standard job format"""
        return {
            "company": job.get("company", ""),
            "title": job.get("position", ""),
            "location": "Remote",
            "link": job.get("url", ""),
            "source": "remoteok",
            "date_posted": job.get("date"),
            "description": job.get("description"),
            "remote": True,
            "tags": job.get("tags", []),
            "sponsorship": None
        }


# ============================================================================
# MAIN ORCHESTRATOR CLASS
# ============================================================================

class Azalea_:
    """
    Main orchestrator/controller for job scraping operations.
    Coordinates multiple job sources and handles data pipeline.
    """
    
    def __init__(self):
        self.jobs = []
        self.helpers = {}
        self._init_helpers()
    
    def _init_helpers(self):
        """Initialize all helper classes for job sources"""
        # Simplify helper (always available)
        self.helpers['simplify'] = SimplifyHelper()
        logger.info("✓ Simplify helper initialized")
        
        # JSearch helper (only if API key available)
        rapidapi_key = os.getenv("RAPIDAPI_KEY")
        if rapidapi_key:
            self.helpers['jsearch'] = JSearchHelper(rapidapi_key)
            logger.info("✓ JSearch helper initialized")
        else:
            logger.warning("⚠ RAPIDAPI_KEY not found. JSearch scraping disabled.")
        
        # RemoteOK helper (always available)
        self.helpers['remoteok'] = RemoteOKHelper()
        logger.info("✓ RemoteOK helper initialized")
    
    def fetch_from_source(self, source: str, **kwargs) -> List[Dict]:
        """
        Fetch jobs from a specific source.
        
        Args:
            source: Source name ('simplify', 'jsearch', 'remoteok')
            **kwargs: Source-specific arguments (e.g., queries for jsearch)
        """
        logger.info("=" * 60)
        logger.info(f"FETCHING FROM: {source.upper()}")
        logger.info("=" * 60)
        
        helper = self.helpers.get(source)
        if not helper:
            logger.warning(f"Helper for '{source}' not available")
            return []
        
        try:
            if source == 'jsearch':
                queries = kwargs.get('queries')
                return helper.fetch_jobs(queries)
            else:
                return helper.fetch_jobs()
        except Exception as e:
            logger.error(f"{source.capitalize()} scraping failed: {e}")
            return []
    
    def fetch_all_sources(self, jsearch_queries: List[str] = None) -> List[Dict]:
        """Fetch jobs from all available sources"""
        all_jobs = []
        
        # Fetch from Simplify
        simplify_jobs = self.fetch_from_source('simplify')
        all_jobs.extend(simplify_jobs)
        
        # Fetch from JSearch (if available)
        if 'jsearch' in self.helpers:
            jsearch_jobs = self.fetch_from_source('jsearch', queries=jsearch_queries)
            all_jobs.extend(jsearch_jobs)
        
        # Fetch from RemoteOK
        remoteok_jobs = self.fetch_from_source('remoteok')
        all_jobs.extend(remoteok_jobs)
        
        logger.info(f"Total jobs fetched from all sources: {len(all_jobs)}")
        return all_jobs
    
    def deduplicate_jobs(self, jobs: List[Dict]) -> List[Dict]:
        """Remove duplicate jobs based on company + title + location"""
        seen = set()
        unique_jobs = []
        
        for job in jobs:
            # Create a unique key
            company = emoji.replace_emoji(job.get("company", ""), replace='').strip().lower()
            title = job.get("title", "").strip().lower()
            location = job.get("location", "").strip().lower()
            
            key = (company, title, location)
            
            if key not in seen and all(key):
                seen.add(key)
                unique_jobs.append(job)
        
        duplicates_removed = len(jobs) - len(unique_jobs)
        logger.info(f"Deduplication: {len(jobs)} → {len(unique_jobs)} jobs ({duplicates_removed} duplicates removed)")
        return unique_jobs
    
    def tag_sponsorship(self, jobs: List[Dict], use_fuzzy: bool = True) -> int:
        """Tag jobs with sponsorship information"""
        try:
            sponsorship_db = SponsorshipDB(csv_paths=[Config.SPONSORSHIP_CSV])
            threshold = Config.FUZZY_THRESHOLD
            
            logger.info(f"Tagging {len(jobs)} jobs with sponsorship info...")
            tagged_count = 0

            for job in jobs:
                company = job.get("company", "")
                
                if use_fuzzy:
                    has_sponsorship = sponsorship_db.fuzzy_match(company, threshold)
                else:
                    has_sponsorship = sponsorship_db.has_sponsorship(company)
                
                job["sponsorship"] = "Likely sponsorship" if has_sponsorship else "No record found"
                
                if has_sponsorship:
                    tagged_count += 1
            
            logger.info(f"Sponsorship tagging complete: {tagged_count}/{len(jobs)} with likely sponsorship")
            return tagged_count
        
        except Exception as e:
            logger.warning(f"Could not load sponsorship database: {e}")
            return 0
    
    def save_to_json(self, jobs: List[Dict], filepath: str = "resources/scraped_jobs.json"):
        """Save jobs to JSON file for backup/debugging"""
        try:
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(jobs, f, indent=2, ensure_ascii=False)
            logger.info(f"✓ Saved {len(jobs)} jobs to {filepath}")
        except Exception as e:
            logger.warning(f"Could not save jobs to JSON: {e}")
    
    def save_to_database(self, jobs: List[Dict]) -> int:
        """Save jobs to PostgreSQL database"""
        logger.info("=" * 60)
        logger.info("SAVING TO DATABASE")
        logger.info("=" * 60)
        
        with JobDatabase() as db:
            inserted = db.insert_jobs_bulk(jobs)
            total_jobs = db.count_jobs()
            logger.info(f"✓ Inserted {inserted} jobs")
            logger.info(f"✓ Total jobs in database: {total_jobs}")
            return inserted
    
    def run(self, sources: List[str] = None, use_fuzzy: bool = True, 
            jsearch_queries: List[str] = None, save_json: bool = True):
        """
        Main orchestration method - coordinates entire scraping pipeline.
        
        Args:
            sources: List of sources to scrape from. None = all available sources
            use_fuzzy: Whether to use fuzzy matching for sponsorship
            jsearch_queries: Custom queries for JSearch (optional)
            save_json: Whether to save results to JSON file
        
        Returns:
            Dictionary with execution statistics
        """
        stats = {
            'simplify': 0,
            'jsearch': 0,
            'remoteok': 0,
            'total_fetched': 0,
            'unique_jobs': 0,
            'inserted': 0,
            'with_sponsorship': 0,
            'errors': 0
        }
        
        try:
            # Step 1: Fetch from sources
            if sources:
                # Fetch only specified sources
                all_jobs = []
                for source in sources:
                    jobs = self.fetch_from_source(source, queries=jsearch_queries if source == 'jsearch' else None)
                    all_jobs.extend(jobs)
            else:
                # Fetch from all available sources
                all_jobs = self.fetch_all_sources(jsearch_queries)
            
            # Count by source
            for job in all_jobs:
                source = job.get("source", "unknown")
                if source in stats:
                    stats[source] += 1
            
            stats['total_fetched'] = len(all_jobs)
            
            if not all_jobs:
                logger.warning("No jobs found to process")
                return stats
            
            # Step 2: Deduplicate
            logger.info("=" * 60)
            logger.info("DEDUPLICATING JOBS")
            logger.info("=" * 60)
            unique_jobs = self.deduplicate_jobs(all_jobs)
            stats['unique_jobs'] = len(unique_jobs)
            self.jobs = unique_jobs
            
            # Step 3: Tag with sponsorship info
            logger.info("=" * 60)
            logger.info("TAGGING SPONSORSHIP")
            logger.info("=" * 60)
            stats['with_sponsorship'] = self.tag_sponsorship(unique_jobs, use_fuzzy)
            
            # Step 4: Save to JSON (optional)
            if save_json:
                self.save_to_json(unique_jobs)
            
            # Step 5: Save to database
            stats['inserted'] = self.save_to_database(unique_jobs)
            
            # Print summary
            self._print_summary(stats)
            
            return stats
            
        except Exception as e:
            stats['errors'] = 1
            logger.error(f"Error in run process: {e}", exc_info=True)
            raise
    
    def _print_summary(self, stats: Dict):
        """Print execution summary"""
        logger.info("=" * 60)
        logger.info("EXECUTION SUMMARY")
        logger.info("=" * 60)
        logger.info("Sources:")
        logger.info(f"  • Simplify GitHub: {stats['simplify']} jobs")
        logger.info(f"  • JSearch API: {stats['jsearch']} jobs")
        logger.info(f"  • RemoteOK API: {stats['remoteok']} jobs")
        logger.info("")
        logger.info("Results:")
        logger.info(f"  • Total fetched: {stats['total_fetched']} jobs")
        logger.info(f"  • After deduplication: {stats['unique_jobs']} jobs")
        logger.info(f"  • Inserted to DB: {stats['inserted']} jobs")
        logger.info(f"  • With sponsorship: {stats['with_sponsorship']} jobs")
        logger.info("=" * 60)


if __name__ == "__main__":
    orchestrator = Azalea_()
    
    # Run with all sources
    orchestrator.run()
    
    # Or run with specific sources only
    # orchestrator.run(sources=['simplify', 'jsearch'])
    
    # Or run with custom JSearch queries
    # orchestrator.run(jsearch_queries=['python intern', 'react intern'])