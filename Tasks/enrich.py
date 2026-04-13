import asyncio
import sys
import os
from Utils.constants import Config
import requests

from Utils.models import Job

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Refine.refine import enrich_unenriched_jobs
from Utils.notify import notify_discord
from Service.db import JobDatabase
async def main():
    #await enrich_unenriched_jobs()
    notify_discord("Enrichment process completed successfully.", file_path="logs/enrich.log")
    db = await JobDatabase.create()
    columns = [ "title", "location", "is_remote", "description", "apply_url", "role_type", "pay_range", "source", "tags"]
    job_list = await db.select(table="job_list",columns=columns, limit=10,order_by="updated_at DESC")
    webhook_url = Config.DISCORD_WEBHOOK
    if not webhook_url:
        return
    for job in job_list:
        payload = Job.build_job_embed(job)
        response = requests.post(webhook_url, json=payload)
        response.raise_for_status()
if __name__ == "__main__":
    asyncio.run(main())