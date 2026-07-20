from abc import ABC, abstractmethod
from typing import Dict, List, Optional
import requests
from Utils.models import Job
from Utils.constants import Config
from Service.db import JobDatabase


class JobSourceBase(ABC):
    def __init__(self):
        self._db: Optional[JobDatabase] = None

    def _fetch(self, url: str, headers: Optional[dict] = None, params: Optional[dict] = None) -> requests.Response:
        response = requests.get(url, headers=headers, params=params, timeout=Config.REQUEST_TIMEOUT)
        response.raise_for_status()
        return response

    async def _upsert_company(self, name: str, company_url: Optional[str] = None) -> dict:
        if self._db is None:
            self._db = await JobDatabase.create()
        data = {"name": name.lower()}
        if company_url:
            data["company_url"] = company_url
        company = await self._db.upsert(table="company", data=data, conflict_column="name")
        if not company:
            company = await self._db.selectOne(table="company", filters={"name": name.lower()})
        return company

    def _make_job(self, refined_job: dict, company: dict) -> Job:
        return Job.from_dict(refined_job, company=company.get("id"))

    async def _map_jobs(self, jobs: List[Dict]) -> List[Job]:
        results = [await self._map_job(job) for job in jobs if job is not None]
        return [j for j in results if j is not None]

    @abstractmethod
    async def _map_job(self, _: Dict) -> Job:
        raise NotImplementedError("Subclasses must implement _map_job method")

    @abstractmethod
    async def fetch_jobs(self, **kwargs) -> List[Job]:
        ...
