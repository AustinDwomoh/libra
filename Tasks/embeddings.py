"""
embed_jobs.py - Standalone embedding + example-bank promotion pass.

Runs independently of scrape/enrich so slow first-call Ollama embedding
loads never block the scraper. Picks up any enriched=true row missing an
embedding, embeds it, and evaluates it for promotion into enrichment_examples.
"""

import asyncio,threading
from tqdm import tqdm
import httpx
from Utils.constants import Config
from Utils.run_logging import get_logger, logged_section, combined_log
from Service.db import JobDatabase
from Utils.notify import notify_discord
from pgvector  import Vector

logger = get_logger(__name__)

OLLAMA_HOST = "http://localhost:11434"

async def embed(text: str) -> Vector:
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{OLLAMA_HOST}/api/embeddings",
            json={"model": "nomic-embed-text", "prompt": text},
        )
        resp.raise_for_status()
        return Vector(resp.json()["embedding"])

async def too_similar_to_existing_example(db: JobDatabase, embedding: Vector, threshold: float = 0.95) -> bool:
    rows = await db.raw(
        sql="""
            SELECT 1 - (embedding <=> $1::vector) AS similarity
            FROM enrichment_examples
            ORDER BY embedding <=> $1::vector
            LIMIT 1
        """,
        params=[embedding],
    )
    if not rows:
        return False
    return rows[0]["similarity"] >= threshold

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

async def maybe_promote_to_example_bank(job: dict, db: JobDatabase, embedding: Vector) -> str:
    """Reuses the embedding already computed for job_list — no re-embedding."""
    if job.get("enrich_attempts", 0) > 1:
        return f"Skip {job.get('id')}: enrich_attempts > 1"
    if not passes_sanity_checks(job):
        return f"Skip {job.get('id')}: failed sanity checks"
    if await too_similar_to_existing_example(db, embedding):
        return f"Skip {job.get('id')}: too similar to existing example"
    job.pop("embedding")
   
    row = await db.upsert(
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
    
    logger.info(f"Promoted {row} to enrichment_examples")
    return f"Promoted {job.get('id')} to enrichment_examples"


def _build_embedding_text(job: dict) -> str:
    parts = [job.get("title") or ""]
    if job.get("description"):
        parts.append(job["description"])
    tags = job.get("tags") or {}
    if isinstance(tags, dict):
        for key in ("skills", "technologies", "requirements"):
            vals = tags.get(key)
            if vals:
                parts.append(", ".join(vals) if isinstance(vals, list) else str(vals))
    return "\n".join(p for p in parts if p)


@logged_section("embedding_pass")
async def run_embedding_pass(batch_size: int = 50) -> dict:
    db = await JobDatabase.create()
    stats = {"attempted": 0, "embedded": 0, "promoted": 0, "errors": 0}
    results = []

    rows = await db.select(
        table="job_list",
        filters={"enriched": True},
        raw_where="enrich_attempts < 5",
        limit=batch_size,
    )

    if not rows:
        logger.info(f"Embedding pass: nothing pending.Rows{len(rows)}")
        return stats

    logger.info(f"Embedding pass: {len(rows)} jobs to embed")
    with tqdm(total=len(rows), desc="Checking jobs", unit="job", ncols=100) as pbar:
        stop_ticker = threading.Event()
        ticker = threading.Thread(
            target=lambda: [
                pbar.refresh() for _ in iter(lambda: stop_ticker.wait(1), True)
            ],
            daemon=True,
        )
        ticker.start()
        for row in rows:
            job = dict(row)
            stats["attempted"] += 1
            try:
                embedding = await embed(_build_embedding_text(job))
                await db.update("job_list", data={"embedding": embedding}, filters={"id": job["id"]})
                stats["embedded"] += 1
                
                result = await maybe_promote_to_example_bank(job, db, embedding)
                results.append(result)
                if result.startswith("Promoted"):
                    stats["promoted"] += 1
                pbar.update(1)
                pbar.set_postfix({
                        "promoted": stats["promoted"],
                        "embedded": stats["embedded"],
                        "errors": stats["errors"],
                       "enrich_attempts": job.get("enrich_attempts", 0)
                    })
            except Exception as e:
                logger.error(f"Embedding pass failed for {job.get('id')}: {e}")
                stats["errors"] += 1
        stop_ticker.set()
        ticker.join()
  

    notify_discord(
        message=f"Embedding pass complete — embedded: {stats['embedded']}, promoted: {stats['promoted']}, errors: {stats['errors']}",
        file_path=str(combined_log()),
    )
    return stats


if __name__ == "__main__":
    asyncio.run(run_embedding_pass())