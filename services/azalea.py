"""
azalea.py - Refactored main orchestrator
"""
import json
import os
from typing import List, Dict, Optional
from dataclasses import dataclass, field

from services.companies import Company, Job
from services.company_db import CompanyDatabase
from services.sponsor import SponsorshipDB
from services.db_manager import JobDatabase
from services.config import Config
from services.jsearch import JSearchHelper
from services.simplify import SimplifyHelper
from services.notify import notify_discord
from services.constants import (
    PositionType, DatePosted, JobSource, SponsorshipStatus,
    StatsKeys, FilePaths, LogMessages, Defaults
)

logger = Config.logger


def remove_emoji(s: str) -> str:
    """Remove emoji from string (with fallback if emoji lib not available)"""
    try:
        import emoji
        return emoji.replace_emoji(s, replace='')
    except Exception:
        return s


@dataclass
class JobStats:
    """Statistics for job scraping operations"""
    simplify: int = 0
    jsearch: int = 0
    remoteok: int = 0
    total_fetched: int = 0
    unique_jobs: int = 0
    inserted: int = 0
    with_sponsorship: int = 0
    errors: int = 0
    position_type: Optional[str] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary for compatibility"""
        return {
            StatsKeys.SIMPLIFY: self.simplify,
            StatsKeys.JSEARCH: self.jsearch,
            StatsKeys.REMOTEOK: self.remoteok,
            StatsKeys.TOTAL_FETCHED: self.total_fetched,
            StatsKeys.UNIQUE_JOBS: self.unique_jobs,
            StatsKeys.INSERTED: self.inserted,
            StatsKeys.WITH_SPONSORSHIP: self.with_sponsorship,
            StatsKeys.ERRORS: self.errors,
            StatsKeys.POSITION_TYPE: self.position_type,
        }

    def reset_source_counts(self):
        """Reset per-source counters"""
        self.simplify = 0
        self.jsearch = 0
        self.remoteok = 0

    def increment_source(self, source: str, count: int):
        """Increment counter for a specific source"""
        if source == JobSource.SIMPLIFY.value:
            self.simplify += count
        elif source == JobSource.JSEARCH.value:
            self.jsearch += count
        elif source == JobSource.REMOTEOK.value:
            self.remoteok += count


class Azalea:
    """Main orchestrator/controller for job scraping operations"""
    
    def __init__(self):
        self.jobs: List[Dict] = []
        self.helpers: Dict[str, any] = {}
        self.stats = JobStats()
        self._init_helpers()
        self.company_cache: set[Company] = set()
    
    def _init_helpers(self):
        """Initialize all helper classes for job sources"""
        # Simplify is always available
        self.helpers[JobSource.SIMPLIFY.value] = SimplifyHelper()
        logger.info(f"✓ {JobSource.SIMPLIFY.value.capitalize()} helper initialized")
        
        # JSearch requires API key
        if Config.J_SEARCH_API_KEY:
            self.helpers[JobSource.JSEARCH.value] = JSearchHelper()
            logger.info(f"✓ {JobSource.JSEARCH.value.capitalize()} helper initialized")
        else:
            logger.warning(f"⚠ {JobSource.JSEARCH.value.capitalize()} API key not found. Scraping disabled.")
    
    def fetch_from_source(
        self, 
        source: str, 
        position_type: str = PositionType.INTERN.value,
        date_posted: str = DatePosted.WEEK.value, 
        **kwargs
    ) -> List[Dict]:
        """Fetch jobs from a specific source"""
        
        self._log_fetch_start(source, position_type, date_posted)
        
        helper = self.helpers.get(source)
        if not helper:
            logger.warning(f"Helper for '{source}' not available")
            return []
        
        try:
            jobs = self._fetch_from_helper(helper, source, position_type, date_posted, **kwargs)
            self.stats.increment_source(source, len(jobs))
            return jobs
            
        except Exception as e:
            logger.error(f"{source.capitalize()} scraping failed: {e}")
            self.stats.errors += 1
            return []

    def _log_fetch_start(self, source: str, position_type: str, date_posted: str):
        """Log the start of a fetch operation"""
        logger.info("=" * 60)
        logger.info(LogMessages.fetch_start(source, position_type, date_posted))
        logger.info("=" * 60)

    def _fetch_from_helper(
        self, 
        helper, 
        source: str, 
        position_type: str, 
        date_posted: str, 
        **kwargs
    ) -> List[Dict]:
        """Fetch jobs from a specific helper"""
        if source == JobSource.JSEARCH.value:
            queries = kwargs.get('queries')
            return helper.fetch_jobs(
                queries, 
                position_type=position_type, 
                date_posted=date_posted
            )
        else:
            return helper.fetch_jobs()

    def fetch_all_sources(
        self, 
        position_type: str = PositionType.INTERN.value, 
        jsearch_queries: Optional[List[str]] = None
    ) -> List[Dict]:
        """Fetch jobs from all available sources"""
        all_jobs = []
        
        # Fetch from Simplify (internships only)
        if position_type in [PositionType.INTERN.value, PositionType.BOTH.value]:
            simplify_jobs = self.fetch_from_source(JobSource.SIMPLIFY.value)
            all_jobs.extend(simplify_jobs)

        # Fetch from JSearch if available
        if JobSource.JSEARCH.value in self.helpers:
            jsearch_jobs = self.fetch_from_source(
                JobSource.JSEARCH.value, 
                position_type=position_type, 
                queries=jsearch_queries
            )
            all_jobs.extend(jsearch_jobs)
        
        self.stats.total_fetched = len(all_jobs)
        logger.info(f"Total positions fetched from all sources: {self.stats.total_fetched}")
        
        return all_jobs
    
    def deduplicate_jobs(self, jobs: List[Job]) -> List[Job]:
        """Remove duplicate jobs based on company + title + location"""
        seen = set()
        unique_jobs = []
        
        for job in jobs:
            key = self._create_job_key(job)
            
            if key not in seen and all(key):
                seen.add(key)
                unique_jobs.append(job)
        
        
        self.stats.unique_jobs = len(unique_jobs)
        
        logger.info(LogMessages.deduplication_result(len(jobs), len(unique_jobs)))
        return unique_jobs

    def _create_job_key(self, job: Dict) -> tuple:
        """Create a unique key for job deduplication"""
        company = remove_emoji(job.get("company", "")).strip().lower()
        title = job.get("title", "").strip().lower()
        location = job.get("location", "").strip().lower()
        return (company, title, location)
    
    def tag_sponsorship(self, jobs: List[Dict], use_fuzzy: bool = True) -> int:
        """Tag jobs with sponsorship information"""
        try:
            sponsorship_db = SponsorshipDB(csv_paths=[Config.SPONSORSHIP_CSV])
            threshold = Config.FUZZY_THRESHOLD
            
            logger.info(f"Tagging {len(jobs)} jobs with sponsorship info...")
            tagged_count = 0

            for job in jobs:
                company = job.get("company", "")
                has_sponsorship = self._check_sponsorship(
                    sponsorship_db, 
                    company, 
                    use_fuzzy, 
                    threshold
                )
                
                job["sponsorship"] = (
                    SponsorshipStatus.LIKELY.value if has_sponsorship 
                    else SponsorshipStatus.NO_RECORD.value
                )
                
                if has_sponsorship:
                    tagged_count += 1
            
            logger.info(LogMessages.sponsorship_tagged(tagged_count, len(jobs)))
            self.stats.with_sponsorship = tagged_count
            return tagged_count
        
        except Exception as e:
            logger.warning(f"Could not load sponsorship database: {e}")
            self.stats.errors += 1
            self.stats.with_sponsorship = 0
            return 0

    def _check_sponsorship(
        self, 
        db: SponsorshipDB, 
        company: str, 
        use_fuzzy: bool, 
        threshold: int
    ) -> bool:
        """Check if company likely sponsors visas"""
        if use_fuzzy:
            return db.fuzzy_match(company, threshold)
        else:
            return db.has_sponsorship(company)
    
    def save_to_json(self, jobs: List[Dict], filepath: str = FilePaths.SCRAPED_JOBS_JSON):
        """Save jobs to JSON file for backup/debugging"""
        try:
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(jobs, f, indent=2, ensure_ascii=False)
            logger.info(f"✓ Saved {len(jobs)} jobs to {filepath}")
        except Exception as e:
            logger.warning(f"Could not save jobs to JSON: {e}")
            self.stats.errors += 1
    
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
            
            self.stats.inserted = inserted
            return inserted
    
    def run(
        self, 
        sources: Optional[List[str]] = None, 
        position_type: str = PositionType.INTERN.value, 
        use_fuzzy: bool = True, 
        jsearch_queries: Optional[List[str]] = None, 
        save_json: bool = True,
        date_posted: str = DatePosted.WEEK.value
    ) -> Dict:
        """Main orchestration method"""
        
        try:
            # Step 1: Fetch from sources
            self.stats.reset_source_counts()
            self.stats.position_type = position_type
            
            all_jobs = self._fetch_jobs(sources, position_type, jsearch_queries, date_posted)
            #probably not the best place for this but whatever
            self.company_cache.add(CompanyDatabase.get_all_sponsors()) # Preload company cache
            if not all_jobs:
                logger.warning("No jobs found to process")
                return self.stats.to_dict()

            # Step 2: Deduplicate
            self._log_section("DEDUPLICATING JOBS")
            unique_jobs = self.deduplicate_jobs(all_jobs)
            self.jobs = unique_jobs
            
            # Step 3: Tag with sponsorship info
            #TODO: SInce the company db now has sponsorship info, consider integrating that in the helpers directly
            self._log_section("TAGGING SPONSORSHIP")
            self.tag_sponsorship(unique_jobs, use_fuzzy)
            
            # Step 4: Save to JSON (optional)
            if save_json:
                self.save_to_json(unique_jobs)
            
            # Step 5: Save to database
            self.save_to_database(unique_jobs)
            
            # Print summary
            self.print_summary()

            return self.stats.to_dict()

        except Exception as e:
            self.stats.errors = 1
            logger.error(f"Error in run process: {e}", exc_info=True)
            raise

    def _fetch_jobs(
        self, 
        sources: Optional[List[str]], 
        position_type: str, 
        jsearch_queries: Optional[List[str]],
        date_posted: str
    ) -> List[Dict]:
        """Fetch jobs from specified or all sources"""
        if sources:
            return self._fetch_from_specific_sources(
                sources, 
                position_type, 
                jsearch_queries,
                date_posted
            )
        else:
            return self.fetch_all_sources(
                position_type=position_type, 
                jsearch_queries=jsearch_queries
            )

    def _fetch_from_specific_sources(
        self, 
        sources: List[str], 
        position_type: str, 
        jsearch_queries: Optional[List[str]],
        date_posted: str
    ) -> List[Dict]:
        """Fetch jobs from a specific list of sources"""
        all_jobs = []
        
        for source in sources:
            kwargs = {'queries': jsearch_queries} if source == JobSource.JSEARCH.value else {}
            jobs = self.fetch_from_source(
                source, 
                position_type=position_type,
                date_posted=date_posted,
                **kwargs
            )
            all_jobs.extend(jobs)
        
        return all_jobs

    def _log_section(self, title: str):
        """Log a section divider"""
        logger.info("=" * 60)
        logger.info(title)
        logger.info("=" * 60)
    
    def print_summary(self):
        """Print execution summary"""
        self._log_section("EXECUTION SUMMARY")
        
        logger.info("Sources:")
        logger.info(f"  • Simplify GitHub: {self.stats.simplify} jobs")
        logger.info(f"  • JSearch API: {self.stats.jsearch} jobs")
        
        logger.info("")
        logger.info("Results:")
        logger.info(f"  • Total fetched: {self.stats.total_fetched} jobs")
        logger.info(f"  • After deduplication: {self.stats.unique_jobs} jobs")
        logger.info(f"  • Inserted to DB: {self.stats.inserted} jobs")
        logger.info(f"  • With sponsorship: {self.stats.with_sponsorship} jobs")
        logger.info("=" * 60)

    def build_discord_message(self, mention_user_id: Optional[str] = None) -> str:
        """Build Discord notification message"""
        lines = []
        
        if mention_user_id:
            lines.append(f"<@{mention_user_id}>")
        
        lines.extend([
            "📢 **Libra Job Scraper Report**",
            "📊 **Job Statistics**",
            f"  • Total fetched: {self.stats.total_fetched} jobs",
            f"  • After deduplication: {self.stats.unique_jobs} jobs",
            f"  • Inserted to DB: {self.stats.inserted} jobs",
            f"  • With sponsorship: {self.stats.with_sponsorship} jobs",
            "",
            "✅ Completed successfully!"
        ])
        
        return "\n".join(lines)


def main():
    """Main entry point for job scraping"""
    orchestrator = Azalea_()
    
    try:
        orchestrator.run(position_type=PositionType.INTERN.value, save_json=True)
        
        message = orchestrator.build_discord_message(mention_user_id="755872891601551511")
        notify_discord(message)

    except Exception as e:
        err_msg = f"❌ Libra scraper failed:\n```{str(e)}```"
        notify_discord(err_msg)


if __name__ == "__main__":
    main()