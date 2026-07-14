"""
Module: remote.py
Description: Fetches remote job listings from RemoteOK API, 
maps them to the standard Job format, and handles company upsert in the database."""


import asyncio,json,requests
from typing import List, Dict
from Utils.constants import Defaults, FilePaths,Config
from Utils.models import Job
from JobSource.base import JobSourceBase

class RemoteOKHelper(JobSourceBase):
    """Helper class for RemoteOK API integration"""

    def __init__(self):
        super().__init__()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
    async def fetch_jobs(self, position_type: str = "intern") -> List[Job]:
        """
        Main method: Fetch jobs from RemoteOK API

        Args:
            position_type: "intern", "fulltime", or "both"
        """
        Config.logger.info(f"RemoteOK: Fetching {position_type} jobs...")
        #TODO: RemoteOK doesn't have a position type filter, so we will fetch all and filter in _map_job based on tags. This is not ideal but RemoteOK's API is limited. We can optimize later if needed.

        try:
            response = self._fetch(Config.REMOTEOK, headers=self.headers)
            raw_jobs = response.json()
            jobs = raw_jobs[1:]  # Skip metadata at index 0
            relevant_jobs = await self._map_jobs(jobs)
            Config.logger.info(f"RemoteOK: Found {len(relevant_jobs)} relevant jobs")
            return relevant_jobs
        except requests.RequestException as e:
            Config.logger.error(f"RemoteOK API error: {e}")
            return []

    async def _map_job(self, job: Dict) -> Job:
        """Map RemoteOK response to standard job format"""
        company = await self._upsert_company(job.get("company") or "unknown")
       

        refined_job = {
            "title": (job.get("position") or "unknown").lower(),
            "location": job.get("location") or Defaults.LOCATION_NOT_SPECIFIED,
            "is_remote": job.get("remote", True),  # RemoteOK only lists remote jobs
            "description": job.get("description", ""),
            "apply_url": job.get("apply_url"),
            "role_type": "internship" if any(tag in job.get("tags", []) for tag in ["intern", "internship"]) else "full-time",
            "salary_range": [job.get("salary_min"), job.get("salary_max")]
                if job.get("salary_min") and job.get("salary_max") else None,
            "source": "remoteok",
            "tags": job.get("tags", []),

        }
        try:
            return self._make_job(refined_job, company)
        except ValueError as e:
            Config.logger.error(f"Error mapping job: {e}")
            return None  #type: ignore

if __name__ == "__main__":
    helper = RemoteOKHelper()
    jobs = asyncio.run(helper.fetch_jobs(position_type="intern"))
    print(f"Total RemoteOK internship jobs fetched: {len(jobs)}")
    with open(FilePaths.REMOTEOK_INTERNSHIPS, "w") as f:
        jobs_dicts = [Job.to_dict(job) for job in jobs if job is not None]  # Filter out any None jobs due to mapping errors
        json.dump(jobs_dicts, f, indent=2)