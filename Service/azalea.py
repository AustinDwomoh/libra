"""
azalea.py - Refactored main orchestrator
"""

import json
from typing import List, Dict, Optional
from uuid import UUID
from JobSource.remote import RemoteOKHelper
from Utils.models import Job, JobStats
from Service.db import JobDatabase
from JobSource.jsearch import JSearch
from Refine.refine import enrich_unenriched_jobs
from JobSource.simplify import Simplify
from Utils.notify import notify_discord
from Utils.constants import (
    PositionType,
    DatePosted,
    JobSource,
    FilePaths,
    LogMessages,Config
)




class Azalea:
    """Main orchestrator/controller for job scraping operations"""

    def __init__(self):
        self.jobs: List[Job] = []
        self.helpers: Dict[JobSource, any] = {} # type: ignore
        self.stats = JobStats()
        self._init_helpers()

    def _init_helpers(self):
        """Initialize all helper classes for job sources"""
        # Simplify is always available
        self.helpers[JobSource.SIMPLIFY] = Simplify()
        Config.logger.info(
            f"✓ {JobSource.SIMPLIFY.value.capitalize()} helper initialized"
        )

        # JSearch requires API key
        if Config.J_SEARCH_API_KEY:
            self.helpers[JobSource.JSEARCH] = JSearch()
            Config.logger.info(
                f"✓ {JobSource.JSEARCH.value.capitalize()} helper initialized"
            )
        else:
            Config.logger.warning(
                f"⚠ {JobSource.JSEARCH.value.capitalize()} API key not found. Scraping disabled."
            )
        if Config.REMOTEOK:
            # Placeholder for future RemoteOK helper
            self.helpers[JobSource.REMOTEOK] = RemoteOKHelper()
            Config.logger.info(
                f"✓ {JobSource.REMOTEOK.value.capitalize()} helper initialized "
            )
        # Placeholder for future RemoteOK helper


    def _log_section(self, title: str):
        """Log a section divider"""
        Config.logger.info("=" * 60)
        Config.logger.info(title)
        Config.logger.info("=" * 60)

    # ============================================================================ #
    #                                   FETCH FN                                   #
    # ============================================================================ #
    async def fetch_from_source(
        self,
        source: JobSource,
        position_type: PositionType = PositionType.INTERN,
        date_posted: DatePosted = DatePosted.WEEK,
        **kwargs,
    ) -> List[Job]:
        """Fetch jobs from a specific source"""

        Config.logger.info("=" * 60)
        Config.logger.info(
            LogMessages.fetch_start(
                source.value, position_type.value, date_posted.value
            )
        )
        Config.logger.info("=" * 60)
        helper = self.helpers.get(source)
        if not helper:
            Config.logger.warning(f"Helper for '{source}' not available")
            return []
        try:
            match source:
                case JobSource.JSEARCH:
                    queries = kwargs.get("queries")
                    jobs = await helper.fetch_jobs(
                        queries, position_type=position_type, date_posted=date_posted
                    )
                case _:
                    jobs = await helper.fetch_jobs()

            self.stats.increment_source(source, len(jobs))
            return jobs
        except Exception as e:
            Config.logger.error(f"{source.value.capitalize()} scraping failed: {e}")
            self.stats.errors += 1
            return []

    async def fetch_all_sources(
        self,
        position_type: PositionType = PositionType.INTERN,
        jsearch_queries: Optional[List[str]] = None,
    ) -> List[Job]:
        """Fetch jobs from all available sources"""
        all_jobs = []

        # Fetch from Simplify (internships only)
        if position_type in [PositionType.INTERN, PositionType.HYBRID]:
            simplify_jobs = await self.fetch_from_source(JobSource.SIMPLIFY)
            all_jobs.extend(simplify_jobs)

        # Fetch from JSearch if available
        if JobSource.JSEARCH in self.helpers:
            jsearch_jobs = await self.fetch_from_source(
                JobSource.JSEARCH, position_type=position_type, queries=jsearch_queries
            )
            all_jobs.extend(jsearch_jobs)

        if JobSource.REMOTEOK in self.helpers:
            remoteok_jobs = await self.fetch_from_source(
                JobSource.REMOTEOK, position_type=position_type
            )
            all_jobs.extend(remoteok_jobs)

        self.stats.total_fetched = len(all_jobs)
        Config.logger.info(
            f"Total positions fetched from all sources: {self.stats.total_fetched}"
        )

        return all_jobs

    # ============================================================================ #
    #                                     Utils                                    #
    # ============================================================================ #

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

        Config.logger.info("=" * 60)

    def build_discord_message(self, mention_user_id: Optional[str] = None) -> str:
        """Build Discord notification message"""
        lines = []

        if mention_user_id:
            lines.append(f"<@{mention_user_id}>")

        lines.extend(
            [
                "📢 **Libra Job Scraper Report**",
                "📊 **Job Statistics**",
                f"  • Total fetched: {self.stats.total_fetched} jobs",
                f"  • After deduplication: {self.stats.unique_jobs} jobs",
                f"  • Inserted to DB: {self.stats.inserted} jobs",
                "",
                "✅ Completed successfully!",
            ]
        )

        return "\n".join(lines)

    async def run(
        self,
        position_type: PositionType = PositionType.INTERN,
        save_json: bool = True,
        jsearch_queries: Optional[List[str]] = None,
        enrich: bool = True,
        enrich_batch_size: int = 50,
        test: bool = False,  # ← when True, skips fetch/dedup and loads from JSON
    ) -> Dict:
        """Main orchestration method"""

        try:
            if not test:
                # ── Step 1: Fetch ────────────────────────────────────────────
                self.stats.reset_source_counts()
                self.stats.position_type = position_type

                all_jobs = await self.fetch_all_sources(
                    position_type=position_type, jsearch_queries=jsearch_queries
                )

                if not all_jobs:
                    Config.logger.warning("No jobs found to process")
                    return self.stats.to_dict()

                # ── Step 2: Deduplicate ──────────────────────────────────────
                self._log_section("DEDUPLICATING JOBS")
                valid_jobs = [job for job in all_jobs if job is not None]
                unique_jobs = list(set(valid_jobs))
                unique_jobs = [job for job in unique_jobs if job.is_valid()]
                self.stats.unique_jobs = len(unique_jobs)
                self.jobs = unique_jobs
                Config.logger.info(
                    LogMessages.deduplication_result(len(all_jobs), len(unique_jobs))
                )

                # ── Step 3: Save JSON (optional) ─────────────────────────────
                if save_json:
                    Config.save_to_json([Job.to_dict(job) for job in unique_jobs])

                list_jobs = [
                    Job.to_dict_for_db(job)
                    for job in unique_jobs
                    if job.title != "unknown"
                ]

            else:
                # ── TEST MODE: skip fetch/dedup, load directly from JSON ─────
                Config.logger.warning("TEST MODE: loading jobs from local JSON, skipping fetch & dedup")
                with open(FilePaths.SCRAPED_JOBS_JSON, "r", encoding="utf-8") as f:
                    list_jobs = json.load(f)[:20]  # type: ignore
                    for job_dict in list_jobs:
                        try:
                            company_id = UUID(job_dict.get("company", None))
                            job = Job.from_dict(job_dict, company=company_id)
                            self.jobs.append(job)
                        except Exception as e:
                            Config.logger.error(f"Error loading job from JSON: {e}")

            # ── Step 4: Insert to DB ─────────────────────────────────────────
            self._log_section("SAVING TO DATABASE")
            db = await JobDatabase.create()
            inserted = await db.bulk_upsert(
                "job_list", list_jobs, conflict_column="identifier"
            )
            self.stats.inserted = len(inserted)
            Config.logger.info(
                f"Inserted {self.stats.inserted} new jobs into the database"
            )

            # ── Step 5: Enrich unenriched jobs via Groq ──────────────────────
            if enrich:
                self._log_section("ENRICHING JOBS (Groq)")
                enrich_stats = await enrich_unenriched_jobs(batch_size=enrich_batch_size)
                Config.logger.info(f"Enrichment stats: {enrich_stats}")

            self.print_summary()
            return self.stats.to_dict()

        except Exception as e:
            self.stats.errors = 1
            Config.logger.error(f"Error in run process: {e}", exc_info=True)
            raise

def main():
    """Main entry point for job scraping"""
    import asyncio

    orchestrator = Azalea()

    try:
        asyncio.run(orchestrator.run(position_type=PositionType.INTERN, save_json=True))

        message = orchestrator.build_discord_message(
            mention_user_id="755872891601551511"
        )
        #notify_discord(message)

    except Exception as e:
        err_msg = f"❌ Libra scraper failed:\n```{str(e)}```"
        notify_discord(err_msg)


if __name__ == "__main__":
    main()
