"""
azalea.py - Refactored main orchestrator
"""
import json
import os
from typing import List, Dict, Optional
from dataclasses import dataclass
import emoji
from services.companies import Company, Job
from services.company_db import CompanyDatabase
from services.db import JobDatabase
from services.config import Config
from services.jsearch import JSearchHelper
from services.simplify import SimplifyHelper
from services.notify import notify_discord
from services.constants import (
    PositionType, DatePosted, JobSource,
    StatsKeys, FilePaths, LogMessages
)





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

    def increment_source(self, source: JobSource, count: int):
        """Increment counter for a specific source"""
        if source == JobSource.SIMPLIFY:
            self.simplify += count
        elif source == JobSource.JSEARCH:
            self.jsearch += count
        elif source == JobSource.REMOTEOK:
            self.remoteok += count


class Azalea:
    """Main orchestrator/controller for job scraping operations"""
    
    def __init__(self):
        self.jobs: List[Dict] = []
        self.helpers: Dict[JobSource, any] = {}
        self.stats = JobStats()
        self._init_helpers()
        self.company_cache: set[Company] = set()
    
    def _init_helpers(self):
        """Initialize all helper classes for job sources"""
        # Simplify is always available
        self.helpers[JobSource.SIMPLIFY] = SimplifyHelper()
        Config.logger.info(f"✓ {JobSource.SIMPLIFY.value.capitalize()} helper initialized")
        
        # JSearch requires API key
        if Config.J_SEARCH_API_KEY:
            self.helpers[JobSource.JSEARCH] = JSearchHelper()
            Config.logger.info(f"✓ {JobSource.JSEARCH.value.capitalize()} helper initialized")
        else:
            Config.logger.warning(f"⚠ {JobSource.JSEARCH.value.capitalize()} API key not found. Scraping disabled.")
    
   # ============================================================================ #
   #                                      LOG                                     #
   # ============================================================================ #

    def _log_fetch_start(self, source: JobSource, position_type: PositionType, date_posted: DatePosted):
        """
        This function logs the start of a data fetch operation with information about the job source,
        position type, and date posted.
        
        :param source: JobSource is an enum representing the source of the job listings 
        :type source: JobSource
        :param position_type: PositionType is an enumeration that represents the type of position being
        fetched. It could be values like full-time, part-time, internship, contract, etc
        :type position_type: PositionType
        :param date_posted: The `date_posted` parameter in the `_log_fetch_start` method is of type
        `DatePosted`. This parameter likely represents the date when a job posting was posted or made
        available
        :type date_posted: DatePosted
        """
        
        Config.logger.info("=" * 60)
        Config.logger.info(LogMessages.fetch_start(source, position_type, date_posted))
        Config.logger.info("=" * 60)
   
    def _log_section(self, title: str):
        """Log a section divider"""
        Config.logger.info("=" * 60)
        Config.logger.info(title)
        Config.logger.info("=" * 60)
    
 # ============================================================================ #
 #                                     SAVE                                     #
 # ============================================================================ #
    def save_to_json(self, jobs: List[Dict], filepath: str = FilePaths.SCRAPED_JOBS_JSON):
        """Save jobs to JSON file for backup/debugging"""
        try:
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(jobs, f, indent=2, ensure_ascii=False)
            Config.logger.info(f"✓ Saved {len(jobs)} jobs to {filepath}")
        except Exception as e:
            Config.logger.warning(f"Could not save jobs to JSON: {e}")
            self.stats.errors += 1
    
    def save_to_database(self, jobs: List[Dict]) -> int:
        """Save jobs to PostgreSQL database"""
        Config.logger.info("=" * 60)
        Config.logger.info("SAVING TO DATABASE")
        Config.logger.info("=" * 60)
        
        with JobDatabase() as db:
            inserted = db.insert_jobs_bulk(jobs)
            total_jobs = db.count_jobs()
            
            Config.logger.info(f"✓ Inserted {inserted} jobs")
            Config.logger.info(f"✓ Total jobs in database: {total_jobs}")
            
            self.stats.inserted = inserted
            return inserted
        

    # ============================================================================ #
    #                                   FETCH FN                                   #
    # ============================================================================ #
    def fetch_from_source( self,  source: JobSource,  position_type: PositionType = PositionType.INTERN, date_posted: DatePosted = DatePosted.WEEK,  **kwargs) -> List[Dict]:
        """Fetch jobs from a specific source"""
        
        self._log_fetch_start(source, position_type, date_posted)
        helper = self.helpers.get(source)
        if not helper:
            Config.logger.warning(f"Helper for '{source}' not available")
            return []
        try:
            match source:
                case JobSource.JSEARCH:
                    queries = kwargs.get('queries')
                    jobs = helper.fetch_jobs( queries,  position_type=position_type,  date_posted=date_posted)
                case _:
                    jobs = helper.fetch_jobs()
            
            self.stats.increment_source(source, len(jobs))
            return jobs
        except Exception as e:
            Config.logger.error(f"{source.value.capitalize()} scraping failed: {e}")
            self.stats.errors += 1
            return []

    def fetch_all_sources( self,  position_type: PositionType = PositionType.INTERN,  jsearch_queries: Optional[List[str]] = None) -> List[Dict]:
        """Fetch jobs from all available sources"""
        all_jobs = []
        
        # Fetch from Simplify (internships only)
        if position_type in [PositionType.INTERN, PositionType.HYBRID]:
            simplify_jobs = self.fetch_from_source(JobSource.SIMPLIFY)
            all_jobs.extend(simplify_jobs)

        # Fetch from JSearch if available
        if JobSource.JSEARCH in self.helpers:
            jsearch_jobs = self.fetch_from_source(JobSource.JSEARCH, position_type=position_type, queries=jsearch_queries)
            all_jobs.extend(jsearch_jobs)
        
        self.stats.total_fetched = len(all_jobs)
        Config.logger.info(f"Total positions fetched from all sources: {self.stats.total_fetched}")
        
        return all_jobs


    # ============================================================================ #
    #                                     Utils                                    #
    # ============================================================================ #

    def deduplicate_jobs(self, jobs: List[Job]) -> List[Job]:
        """
        The `deduplicate_jobs` function removes duplicate jobs from a list based on company, title, and
        location.
        
        :param jobs: A list of Job objects that you want to deduplicate based on the combination of
        company, title, and location
        :type jobs: List[Job]
        :return: The `deduplicate_jobs` method returns a list of unique Job objects after removing any
        duplicates based on the combination of company, title, and location attributes.
        """
        """Remove duplicate jobs based on company + title + location"""
        seen = set()
        unique_jobs = []
        
        for job in jobs:
            key = self._create_job_key(job)
            
            if key not in seen and all(key):
                seen.add(key)
                unique_jobs.append(job)
        
        
        self.stats.unique_jobs = len(unique_jobs)
        
        Config.logger.info(LogMessages.deduplication_result(len(jobs), len(unique_jobs)))
        return unique_jobs

    def _create_job_key(self, job: Dict) -> tuple:
        """Create a unique key for job deduplication"""
        company = emoji.replace_emoji(job.get("company", ""), replace='').strip().lower() 
        title = emoji.replace_emoji(job.get("title", ""), replace='').strip().lower()
        location = emoji.replace_emoji(job.get("location", ""), replace='').strip().lower()
        return (company, title, location)

    def print_summary(self):
        """Print execution summary"""
        self._log_section("EXECUTION SUMMARY")
        
        Config.logger.info("Sources:")
        Config.logger.info(f"  • Simplify GitHub: {self.stats.simplify} jobs")
        Config.logger.info(f"  • JSearch API: {self.stats.jsearch} jobs")
        
        Config.logger.info("")
        Config.logger.info("Results:")
        Config.logger.info(f"  • Total fetched: {self.stats.total_fetched} jobs")
        Config.logger.info(f"  • After deduplication: {self.stats.unique_jobs} jobs")
        Config.logger.info(f"  • Inserted to DB: {self.stats.inserted} jobs")
        Config.logger.info(f"  • With sponsorship: {self.stats.with_sponsorship} jobs")
        Config.logger.info("=" * 60)

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

    def run(self,  position_type: PositionType = PositionType.INTERN,  save_json: bool = True, jsearch_queries: Optional[List[str]] = None) -> Dict:
        """Main orchestration method"""
        
        try:
            # Step 1: Fetch from sources
            self.stats.reset_source_counts()
            self.stats.position_type = position_type
            
            all_jobs = self.fetch_all_sources(position_type=position_type, jsearch_queries=jsearch_queries)
            #probably not the best place for this but whatever
            self.company_cache.add(CompanyDatabase.get_all_sponsors()) # Preload company cache
            if not all_jobs:
                Config.logger.warning("No jobs found to process")
                return self.stats.to_dict()

            # Step 2: Deduplicate
            self._log_section("DEDUPLICATING JOBS")
            unique_jobs = self.deduplicate_jobs(all_jobs)
            self.jobs = unique_jobs
          
            
            # Step 3: Save to JSON (optional)
            if save_json:
                self.save_to_json(unique_jobs)
            
            # Step 5``: Save to database
            self.save_to_database(unique_jobs)
            
            # Print summary
            self.print_summary()

            return self.stats.to_dict()

        except Exception as e:
            self.stats.errors = 1
            Config.logger.error(f"Error in run process: {e}", exc_info=True)
            raise



def main():
    """Main entry point for job scraping"""
    orchestrator = Azalea()
    
    try:
        orchestrator.run(position_type=PositionType.INTERN, save_json=True)
        
        message = orchestrator.build_discord_message(mention_user_id="755872891601551511")
        notify_discord(message)

    except Exception as e:
        err_msg = f"❌ Libra scraper failed:\n```{str(e)}```"
        notify_discord(err_msg)


if __name__ == "__main__":
    main()