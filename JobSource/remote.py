import asyncio,json,requests
from typing import List, Dict
from Service.db import JobDatabase
from Utils.constants import Defaults, FilePaths,Config
from Utils.models import Job

class RemoteOKHelper:
    """Helper class for RemoteOK API integration"""
   
    def __init__(self):
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

        try:
            response = requests.get(
                Config.REMOTEOK,
                headers=self.headers,
                timeout=Config.REQUEST_TIMEOUT
            )
            response.raise_for_status()
            raw_jobs = response.json()
            jobs = response.json()[1:]  # Skip metadata at index 0
            relevant_jobs = [
               await self._map_job(job) for job in jobs if job is not None    ]
    
            Config.logger.info(f"RemoteOK: Found {len(relevant_jobs)} relevant jobs")
            return relevant_jobs
           
        except requests.RequestException as e:
           Config.logger.error(f"RemoteOK API error: {e}")
           return []

    async def _map_job(self, job: Dict) -> Job:
        """Map JSearch response to standard job format"""
        compnay_dict = {
            "name": (job.get("company") or "unknown").lower(),
        }
        DB = await JobDatabase.create()

        company = await DB.upsert(table="company",data = compnay_dict)  # Upsert company and get the record with ID
        if not company:
            company = await DB.selectOne(table="company", filters={"name": compnay_dict["name"]})
       

        refined_job = {
            "title": job.get("position").lower(), # type: ignore
            "location": job.get("location") or Defaults.LOCATION_NOT_SPECIFIED,
            "is_remote": job.get("remote", True),  # RemoteOK only lists remote jobs
            "description": job.get("description", ""),
            "apply_url": job.get("apply_url") ,
            "role_type": "internship" if any(tag in job.get("tags", []) for tag in ["intern", "internship"]) else "full-time",
            "salary_range": [job.get("salary_min"), job.get("salary_max")]
                if job.get("salary_min") and job.get("salary_max") else None,
            "source": "remoteok",
            "tags": job.get("tags", []),

        }
        #print(f"Mapped job: {refined_job}")
        try:
            njob = Job.from_dict(refined_job, company=company.get("id"))
        except ValueError as e:
            Config.logger.error(f"Error mapping job: {e}")
            return None #type: ignore  #return empty to avoid breaking the loop, we can filter out invalid jobs later
                
        return njob  

if __name__ == "__main__":
    helper = RemoteOKHelper()
    jobs = asyncio.run(helper.fetch_jobs(position_type="intern"))
    print(f"Total RemoteOK internship jobs fetched: {len(jobs)}")
    with open(FilePaths.REMOTEOK_INTERNSHIPS, "w") as f:
        jobs_dicts = [job.to_dict(job) for job in jobs]
        json.dump(jobs_dicts, f, indent=2)