"""
enrich_pipeline.py - Post-insert enrichment pass using Ollama.

Queries the DB for jobs where enriched=false, runs the extractor pipeline
(regex → LLM → optional scrape), updates the row, and marks enriched=true.

Never re-calls Ollama on a job that has already been enriched.
"""

import asyncio,uuid
from typing import Optional
from Utils.constants import Config
from Service.db import JobDatabase
from Refine.extractor import JobEnricher
from Refine.llm import OllamaProvider, LLMProvider, LLMParseError
from Utils.models import Job


# Fields we want  to fill. Enrichment is skipped entirely if all are present.
ENRICH_FIELDS = ("description", "is_remote", "role_type", "pay_range", "tags")

# How many times we'll retry a job that fails with an LLMParseError (the
# model's output was unparseable, even after repair) before giving up on it.
MAX_ENRICH_ATTEMPTS = 3


def _needs_enrichment(row: dict) -> bool:
    """Return True if any target field is missing on a DB row."""
    return any(Config.is_missing(row.get(f)) for f in ENRICH_FIELDS)


def _row_to_job(row: dict) -> Job:
    """Reconstruct a Job instance from a DB row (enough for extractor)."""
    return Job(
        title=row["title"] or "unknown",
        company=row["company"],          # already a UUID from asyncpg
        location=row["location"] or "Unknown",
        is_remote=row.get("is_remote"),
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
        provider:       LLM provider instance. Defaults to OllamaProvider().
        use_llm:        Whether to call Ollama at all (regex always runs).
        scrape_if_empty: Whether to Playwright-scrape apply_url as last resort.
        batch_size:     Max jobs to enrich per run (guards against Ollama rate limits).
        llm_delay:      Seconds between Ollama calls.

    Returns:
        {"attempted": int, "enriched": int, "skipped": int, "errors": int}
    """
    if use_llm and provider is None:
        provider = OllamaProvider()

    db = await JobDatabase.create()
    stats = {"attempted": 0, "enriched": 0, "skipped": 0, "errors": 0, "gave_up": 0}

    # Pull a batch of unenriched jobs
    rows = await db.select(
        table="job_list",
        filters={"enriched": False, "status": "active"},
        order_by="created_at DESC",
        limit=batch_size,
    ) #the idea is to always newer jobs first, so we can get the most recent jobs enriched first as they are the ones that are more likely to be relevant and useful for users. This way, we can prioritize enriching the jobs that are more likely to be applied to and increase the chances of successful placements.
    
    if not rows:
        Config.logger.info("Enrichment: no unenriched jobs found.")
        return stats

    Config.logger.info(f"Enrichment: {len(rows)} jobs to process (batch_size={batch_size})")
    ENRICHED = []
    for i, row in enumerate(rows):
        stats["attempted"] += 1
        job_id = row["id"]
        enricher = JobEnricher(job_id=job_id, provider=provider, use_llm=use_llm)
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
            meta = await enricher.enrich_job(job)
            Config.logger.debug(f"Job item after enrichment {job_id}: {job}")
            Config.logger.debug(f"Enrichment [{i+1}/{len(rows)}] {job.title}: {meta['fields_filled']}")
        except LLMParseError as e:
            # The model's output was unparseable even after repair attempts.
            # This is more likely a persistent issue (bad model, weird input
            # text) than a one-off blip — cap retries so we don't loop on it
            # forever.
            attempts = (row.get("enrich_attempts") or 0) + 1
            if attempts >= MAX_ENRICH_ATTEMPTS:
                Config.logger.warning(
                    f"Enrichment: giving up on job {job_id} after {attempts} "
                    f"unparseable LLM responses: {e}"
                )
                await db.update(
                    "job_list",
                    data={"enriched": True, "enrich_attempts": attempts},
                    filters={"id": job_id},
                )
                stats["gave_up"] += 1
            else:
                Config.logger.warning(
                    f"Enrichment: unparseable LLM response for job {job_id} "
                    f"(attempt {attempts}/{MAX_ENRICH_ATTEMPTS}), will retry: {e}"
                )
                await db.update(
                    "job_list",
                    data={"enrich_attempts": attempts},
                    filters={"id": job_id},
                )
            stats["errors"] += 1
            continue
        except Exception as e:
            # Network errors, rate limits, DB hiccups, etc. — treat as
            # transient and don't count against the job; just retry next run.
            Config.logger.error(f"Enrichment: enrich_job failed for {job_id}: {e}")
            stats["errors"] += 1
            # Don't mark enriched — will retry next run
            continue

        # Persist enriched fields + set enriched=true
        try:
            payload = Job.to_dict_for_db(job)
            payload["enriched"] = True
            payload["enrich_attempts"] = (row.get("enrich_attempts") or 0) + 1
            Config.logger.debug(f"Updating job {job_id}: {payload}")

            re = await db.upsert("job_list", payload, conflict_column=["company", "location", "title", "apply_url"])
            stats["enriched"] += 1
            ENRICHED.append(re)
        except Exception as e:
            Config.logger.error(f"Enrichment: DB update failed for {job_id}: {e}")
            stats["errors"] += 1

       
        #The idea is to keep the rows returned after the enrichment process in memory so that we can avoid re-enriching them in the same run. 
        #As we will be using them to build the enrichment examples for the RAG pipeline. T
        if use_llm and i < len(rows) - 1:
            await asyncio.sleep(llm_delay)

    for payload in ENRICHED:
        try:
            await maybe_promote_to_example_bank(payload, db)
        except Exception as e:
            Config.logger.error(f"Example bank promotion failed for {payload.get('id')}: {e}")
    Config.logger.info(
        f"Enrichment complete — attempted: {stats['attempted']}, "
        f"enriched: {stats['enriched']}, skipped: {stats['skipped']}, "
        f"errors: {stats['errors']}, gave_up: {stats['gave_up']}"
    )
    return stats

async def too_similar_to_existing_example(db: JobDatabase, embedding: list[float], threshold: float = 0.95) -> bool:
    row = await db.raw(
        sql=f"""
            SELECT 1 - (embedding <=> $1::vector) AS similarity
            FROM enrichment_examples
            ORDER BY embedding <=> $1::vector
            LIMIT 1
        """,
        params=[embedding],
    )
    return bool(row and row["similarity"] >= threshold) #type: ignore

def passes_sanity_checks(job: dict) -> bool:
    if job.get("role_type") not in {"internship", "fulltime", "parttime", "contract"}:
        return False
    pay = job.get("pay_range")
    if pay is not None:
        if not (isinstance(pay, list) and len(pay) == 2):
            return False
        lo, hi = pay
        if not (isinstance(lo, (int, float)) and isinstance(hi, (int, float))):
            return False
        if lo > hi or lo < 0:
            return False
    if not job.get("location") or job["location"] == "Unknown":
        return False
    if not job.get("description") or len(job["description"]) < 50:
        return False
    return True
import httpx

async def embed(text: str) -> list[float]:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"http://localhost:11434/api/embeddings",
            json={"model": "nomic-embed-text", "prompt": text},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["embedding"]

async def maybe_promote_to_example_bank(job: dict, db: JobDatabase):
    Config.logger.debug(f"Checking if job {job.get('id')} should be promoted to example bank")
    if job.get("enrich_attempts", 0) > 1:
        return
    if not passes_sanity_checks(job):
        return
    embedding = await embed(job.get("description")) #type: ignore
    if await too_similar_to_existing_example(db, embedding):
        return
    await db.upsert(
        "enrichment_examples",
        {
            "source_job_id": job["id"],
            "raw_description": job.get("description"),
            "extracted_json": job,
            "embedding": embedding,
            "verified_by": "auto_clean_pass",
        },
        conflict_column=["source_job_id"],
    )
    Config.logger.info(f"Promoted job {job.get('id')} to enrichment_examples bank")
async def _mark_enriched(db: JobDatabase, job_id: uuid.UUID):
    """Mark a job as enriched without changing other fields."""
    await db.update("job_list", data={"enriched": True}, filters={"id": job_id})