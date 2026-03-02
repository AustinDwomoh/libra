import asyncio

import requests
from typing import List, Dict
from services.config import Config
from services.constants import Defaults
from services.companies import Job
from services.db import JobDatabase

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
            with open("remoteok_raw.json", "w") as f:
                import json
                json.dump(raw_jobs, f, indent=2)
            jobs = response.json()[1:]  # Skip metadata at index 0
            with open("remoteok_before_jobs.json", "w") as f:
                import json
                json.dump(jobs, f, indent=2)
            # Filter based on position type
            relevant_jobs = [
               await self._map_job(job) for job in jobs           ]
          # if self._is_relevant_job(job, position_type)
            Config.logger.info(f"RemoteOK: Found {len(relevant_jobs)} relevant jobs")
            return relevant_jobs
           
        except requests.RequestException as e:
           Config.logger.error(f"RemoteOK API error: {e}")
           return []
   
    def _is_relevant_job(self, job: Dict, position_type: str = "intern") -> bool:
       """Check if job matches the requested position type"""
       position = job.get("position", "").lower()
       tags = [t.lower() for t in job.get("tags", [])]
       
       # Internship keywords
       internship_keywords = ["intern", "internship"]
       is_internship = any(kw in position or kw in tags for kw in internship_keywords)
       
       # Entry-level/Junior keywords
       entry_keywords = ["entry level", "junior", "graduate", "new grad"]
       is_entry = any(kw in position for kw in entry_keywords)
       
       # Relevant tech roles
       relevant_keywords = ["frontend", "backend", "fullstack", "data", "software", 
                          "web", "developer", "engineer", "designer", "analyst"]
       is_relevant_tech = any(kw in position or kw in tags for kw in relevant_keywords)
       
       # Filter based on position_type
       if position_type == "intern":
           return is_internship and is_relevant_tech
       elif position_type == "fulltime":
           return (is_entry or is_relevant_tech) and not is_internship
       else:  # both
           return is_relevant_tech and (is_internship or is_entry or True)
   
    async def _map_job(self, job: Dict) -> Job:
        """Map JSearch response to standard job format"""
        compnay_dict = {
            "name": job.get("company").lower(),
        }
        DB = await JobDatabase.create()

        company = await DB.upsert(table="company",data = compnay_dict)  # Upsert company and get the record with ID
        if not company:
            company = await DB.selectOne(table="company", filters={"name": compnay_dict["name"]})
       

        refined_job = {
            "title": job.get("job_title", "Unknown").lower(),
            "location": job.get("location") or Defaults.LOCATION_NOT_SPECIFIED,
            "is_remote": job.get("job_is_remote", False),
            "description": job.get("description", ""),
            "apply_url": job.get("apply_url") ,
            "role_type": "internship" if any(tag in job.get("tags", []) for tag in ["intern", "internship"]) else "full-time",
            "salary_range": f"{job.get('salary_min', 'N/A')} - {job.get('salary_max', 'N/A')} $",
            "source": "remoteok",
            "tags": job.get("tags", []),
            "date_posted": job.get("date"),

        }
   
        return Job.from_dict(refined_job, company=company.get("id"))

if __name__ == "__main__":
    helper = RemoteOKHelper()
    jobs = asyncio.run(helper.fetch_jobs(position_type="intern"))
    print(f"Total RemoteOK internship jobs fetched: {len(jobs)}")
    with open("remoteok_internships.json", "w") as f:
        import json
        jobs_dicts = [job.to_dict(job) for job in jobs]
        json.dump(jobs_dicts, f, indent=2)