import emoji ,json, os
from sponsor import SponsorshipDB
from services.db_manager import JobDatabase
from typing import List, Dict
from services.config import Config
from services.jsearch import JSearchHelper
from services.simplify import SimplifyHelper
 
logger = Config.logger

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
        self.helpers['simplify'] = SimplifyHelper()
        logger.info("✓ Simplify helper initialized")
        j_search_key = Config.J_SEARCH_API_KEY
        print(f"JSearch API Key: {j_search_key}")
        if j_search_key:
            self.helpers['jsearch'] = JSearchHelper()
            logger.info("✓ JSearch helper initialized")
        else:
            logger.warning("⚠ JSearch API key not found. JSearch scraping disabled.")
    
    def fetch_from_source(self, source: str, position_type: str = "intern",date_posted: str = "week", **kwargs) -> List[Dict]:
        """
        Fetch jobs from a specific source.
        
        Args:
            source: Source name ('simplify', 'jsearch', 'remoteok')
            position_type: "intern", "fulltime", or "both"
            date_posted: "all", "today", "3days", "week", "month"
            **kwargs: Source-specific arguments
        """
        logger.info("=" * 60)
        logger.info(f"FETCHING FROM: {source.upper()} ({position_type}, posted: {date_posted})")
        logger.info("=" * 60)
        
        helper = self.helpers.get(source)
        if not helper:
            logger.warning(f"Helper for '{source}' not available")
            return []
        
        try:
            if source == 'jsearch':
                queries = kwargs.get('queries')
                return helper.fetch_jobs(queries, position_type=position_type, date_posted=date_posted)
            else:
    
                return helper.fetch_jobs()
        except Exception as e:
            logger.error(f"{source.capitalize()} scraping failed: {e}")
            return []
        

    def fetch_all_sources(self, position_type: str = "intern", jsearch_queries: List[str] = None) -> List[Dict]:
        """
        Fetch jobs from all available sources
        
        Args:
            position_type: "intern", "fulltime", or "both"
            jsearch_queries: Custom queries for JSearch
        """
        all_jobs = []
        
        if position_type in ["intern", "both"]:
            simplify_jobs = self.fetch_from_source('simplify')
            all_jobs.extend(simplify_jobs)

        if 'jsearch' in self.helpers:
            jsearch_jobs = self.fetch_from_source('jsearch', position_type=position_type, queries=jsearch_queries)
            all_jobs.extend(jsearch_jobs)
        
        logger.info(f"Total positions fetched from all sources: {len(all_jobs)}")
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
    
    def run(self, sources: List[str] = None, position_type: str = "intern", use_fuzzy: bool = True, jsearch_queries: List[str] = None, save_json: bool = True,date_posted:str="week") -> Dict:
        """
        Main orchestration method
        
        Args:
            sources: List of sources to scrape from
            position_type: "intern", "fulltime", or "both"
            use_fuzzy: Whether to use fuzzy matching for sponsorship
            jsearch_queries: Custom queries for JSearch
            save_json: Whether to save results to JSON file
        """
        stats = {
            'simplify': 0,
            'jsearch': 0,
            #'remoteok': 0,
            'total_fetched': 0,
            'unique_jobs': 0,
            'inserted': 0,
            'with_sponsorship': 0,
            'errors': 0,
            'position_type': position_type
        }
        
        try:
            # Fetch from sources
            if sources:
                all_jobs = []
                for source in sources:
                    jobs = self.fetch_from_source(source, position_type=position_type, 
                                                queries=jsearch_queries if source == 'jsearch' else None)
                    all_jobs.extend(jobs)
            else:
                all_jobs = self.fetch_all_sources(position_type=position_type, jsearch_queries=jsearch_queries)
            
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
        #logger.info(f"  • RemoteOK API: {stats['remoteok']} jobs")
        logger.info("")
        logger.info("Results:")
        logger.info(f"  • Total fetched: {stats['total_fetched']} jobs")
        logger.info(f"  • After deduplication: {stats['unique_jobs']} jobs")
        logger.info(f"  • Inserted to DB: {stats['inserted']} jobs")
        logger.info(f"  • With sponsorship: {stats['with_sponsorship']} jobs")
        logger.info("=" * 60)


if __name__ == "__main__":
    orchestrator = Azalea_()
    
    print("\n" + "="*60)
    print("LIBRA JOB SCRAPER")
    print("="*60)
    
    # 1. Fetch internships only
    print("\n[1/3] Fetching INTERNSHIPS...")
    orchestrator.run(position_type="intern", save_json=True)
    
    input("\n✓ Internships complete. Press Enter to fetch full-time jobs...")
    
    # 2. Fetch full-time jobs only
    print("\n[2/3] Fetching FULL-TIME JOBS...")
    orchestrator.run(position_type="fulltime", save_json=True)
    
    input("\n✓ Full-time jobs complete. Press Enter to fetch both...")
    
    # 3. Fetch both (to catch hybrid positions)
    print("\n[3/3] Fetching BOTH (including hybrid positions)...")
    orchestrator.run(position_type="both", save_json=True)
    
    print("\n" + "="*60)
    print("✓ ALL SCRAPING COMPLETE")
    print("="*60)
    
    # Optional: Run with custom queries
    # orchestrator.run(
    #     position_type="both",
    #     jsearch_queries=["software engineer chicago", "data scientist remote"]
    # )