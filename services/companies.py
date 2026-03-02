from dataclasses import dataclass, field
from typing import Optional, List

import uuid


@dataclass
class Company:
    name: str
    db_id: Optional[int] = None
    #sponsorships: bool = False
    company_url: Optional[str] = None

    def __post_init__(self):
        if not self.name or len(self.name) < 1:
            raise ValueError("Company name is required")
     
    def is_valid(self) -> bool:
        return bool(self.name and self.location)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
        #    "sponsorships": self.sponsorships,
            "company_url": self.company_url,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Company":
        return cls(
            name=data.get("name", "Unknown"),
            db_id=data.get("id"),
        #    sponsorships=data.get("sponsorships", False),
            company_url=data.get("company_url"),
        )


@dataclass
class Job:
    #TODO: Validate the date collectons and make sure they are in the correct format (e.g. ISO 8601)
    #TODO: Add a field for the job ID (if we want to store it in the database) and make sure it is unique
    #TODO: Make sure all helpers are are consistent with this data model (e.g. the company field should be a Company object, not just an ID)
    title: str
    location: str
    is_remote: bool
    description: str
    company: uuid.UUID = None  # This should be the company ID, not the full object, to avoid circular references
    apply_url: Optional[str] = None
    role_type: str = "other"
    pay_range: Optional[tuple] = None
    date_posted: Optional[str] = None
    source: str = "unknown"
    tags: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        if not self.title:
            raise ValueError("Job title is required")
        if not isinstance(self.company, uuid.UUID):
            raise ValueError("Company must be a UUID representing the company ID")
        if not self.location:
            self.location = "Unknown"

    def is_valid(self) -> bool:
        return bool(
            self.title
            and isinstance(self.company, uuid.UUID)
            and self.location
            and self.apply_url or  self.description
        )

    def get_salary_info(self) -> str:
        if not self.pay_range:
            return "Not specified"
        min_sal, max_sal = self.pay_range
        return f"${min_sal:,} - ${max_sal:,}"


    @classmethod
    def from_dict(cls, job: dict, company: uuid.UUID) -> "Job":
        """
        Convert a raw job dictionary into a Job instance.
        Requires a resolved Company object (look it up by company_id before calling this).
        """
        salary_range = job.get("salary_range")
        pay_range = (
            tuple(salary_range)
            if isinstance(salary_range, (tuple, list)) and len(salary_range) == 2
            else None
        )

        return cls(
            title=job.get("title", ""),
            company=company,
            location=job.get("location", "Unknown"),
            is_remote=job.get("remote", False),
            description=job.get("description", ""),
            apply_url=job.get("link") or job.get("apply_url"),
            role_type=job.get("role_type", "other"),
            pay_range=pay_range,
            date_posted=job.get("date_posted"),
            source=job.get("source", "unknown"),
            tags=job.get("tags", {}),
        )

    @classmethod
    def to_dict(cls, job: "Job") -> dict:
        return {
            "title": job.title,
            "company": str(job.company) if job.company else None,
            "location": job.location,
            "is_remote": job.is_remote,
            "description": job.description,
            "apply_url": job.apply_url,
            "role_type": job.role_type,
            "pay_range": job.pay_range,
            "date_posted": job.date_posted,
            "source": job.source,
            "tags": job.tags,
        }
 
    

    def __eq__(self, other):
        if not isinstance(other, Job):
            return False
        return (
            self.title == other.title
            and self.company == other.company
            and self.location == other.location
            and self.apply_url == other.apply_url
        )
    
    def __hash__(self):
        return hash((self.title, self.company, self.location, self.apply_url))