"""
enrich_pipeline.py - Post-insert enrichment pass using Groq.

Queries the DB for jobs where enriched=false, runs the extractor pipeline
(regex → LLM → optional scrape), updates the row, and marks enriched=true.

Never re-calls Groq on a job that has already been enriched.
"""

import asyncio,uuid
from typing import Optional
from Utils.constants import Config
from Service.db import JobDatabase
from Refine.extractor import enrich_job
from Refine.llm import GroqProvider, LLMProvider
from Utils.models import Job


# Fields we want Groq to fill. Enrichment is skipped entirely if all are present.
ENRICH_FIELDS = ("description", "is_remote", "role_type", "pay_range", "tags")


def _needs_enrichment(row: dict) -> bool:
    """Return True if any target field is missing on a DB row."""
    return any(Config.is_missing(row.get(f)) for f in ENRICH_FIELDS)


def _row_to_job(row: dict) -> Job:
    """Reconstruct a Job instance from a DB row (enough for extractor)."""
    return Job(
        title=row["title"] or "unknown",
        company=row["company"],          # already a UUID from asyncpg
        location=row["location"] or "Unknown",
        is_remote=row.get("is_remote", False),
        description=row.get("description") or "",
        apply_url=row.get("apply_url"),
        role_type=row.get("role_type") or "other",
        pay_range=row.get("pay_range"),
        source=row.get("source") or "unknown",
        tags=row.get("tags") or {},
    )





async def enrich_unenriched_jobs(
    provider: Optional[LLMProvider] = None,
    use_llm: bool = True,
    batch_size: int = 20,
    llm_delay: float = 0.5,
) -> dict:
    """
    Main entry point.  Call this after bulk_upsert in azalea.run().

    Args:
        provider:       LLM provider instance. Defaults to GroqProvider().
        use_llm:        Whether to call Groq at all (regex always runs).
        scrape_if_empty: Whether to Playwright-scrape apply_url as last resort.
        batch_size:     Max jobs to enrich per run (guards against Groq rate limits).
        llm_delay:      Seconds between Groq calls.

    Returns:
        {"attempted": int, "enriched": int, "skipped": int, "errors": int}
    """
    if use_llm and provider is None:
        provider = GroqProvider()

    db = await JobDatabase.create()
    stats = {"attempted": 0, "enriched": 0, "skipped": 0, "errors": 0}

    # Pull a batch of unenriched jobs
    rows = await db.select(
        table="job_list",
        filters={"enriched": False},
        order_by="created_at ASC",
        limit=batch_size,
    )
    
    if not rows:
        Config.logger.info("Enrichment: no unenriched jobs found.")
        return stats

    Config.logger.info(f"Enrichment: {len(rows)} jobs to process (batch_size={batch_size})")

    for i, row in enumerate(rows):
        stats["attempted"] += 1
        job_id = row["id"]

        # Fast-path: if nothing is actually missing, just mark enriched and move on
        if not _needs_enrichment(row):
            await _mark_enriched(db, job_id)
            stats["skipped"] += 1
            continue
        
        try:
            job = _row_to_job(row)
        except (ValueError, KeyError) as e:
            Config.logger.warning(f"Enrichment: could not reconstruct job {job_id}: {e}")
            await _mark_enriched(db, job_id)   # don't retry broken rows forever
            stats["errors"] += 1
            continue

        try:
            Config.logger.debug(f"Job item before enrichment {job_id}: {job}")
            meta = await enrich_job(
                job,
                provider=provider,
                use_llm=use_llm,
            )
            Config.logger.debug(f"Job item after enrichment {job_id}: {job}")
            Config.logger.debug(f"Enrichment [{i+1}/{len(rows)}] {job.title}: {meta['fields_filled']}")
        except Exception as e:
            Config.logger.error(f"Enrichment: enrich_job failed for {job_id}: {e}")
            stats["errors"] += 1
            # Don't mark enriched — will retry next run
            continue

        # Persist enriched fields + set enriched=true
        try:
            payload = Job.to_dict_for_db(job)
            payload["enriched"] = True
            Config.logger.debug(f"Updating job {job_id}: {payload}")

            await db.upsert("job_list", payload, conflict_column=["title", "company", "apply_url"])
            stats["enriched"] += 1
        except Exception as e:
            Config.logger.error(f"Enrichment: DB update failed for {job_id}: {e}")
            stats["errors"] += 1

        # Respect Groq free-tier rate limits
        if use_llm and i < len(rows) - 1:
            await asyncio.sleep(llm_delay)

    Config.logger.info(
        f"Enrichment complete — attempted: {stats['attempted']}, "
        f"enriched: {stats['enriched']}, skipped: {stats['skipped']}, "
        f"errors: {stats['errors']}"
    )
    return stats




async def _mark_enriched(db: JobDatabase, job_id: uuid.UUID):
    """Mark a job as enriched without changing other fields."""
    await db.update("job_list", data={"enriched": True}, filters={"id": job_id})