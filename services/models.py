from dataclasses import dataclass, field
import datetime
from typing import Optional, List

import uuid


@dataclass
class Company:
    name: str
    db_id: Optional[int] = None
    company_url: Optional[str] = None

    def __post_init__(self):
        if not self.name or len(self.name) < 1:
            raise ValueError("Company name is required")

    def is_valid(self) -> bool:
        return bool(self.name)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "company_url": self.company_url,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Company":
        return cls(
            name=data.get("name", "Unknown"),
            db_id=data.get("id"),
            company_url=data.get("company_url"),
        )


@dataclass
class Job:
    title: str
    location: str
    is_remote: bool
    description: str
    company: uuid.UUID = None  # company ID (UUID), not the full object
    apply_url: Optional[str] = None
    role_type: str = "other"
    pay_range: Optional[list] = None
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
            and (self.apply_url or self.description)
        )

    def get_salary_info(self) -> str:
        if not self.pay_range:
            return "Not specified"
        min_sal, max_sal = self.pay_range[0], self.pay_range[1]
        if min_sal is None and max_sal is None:
            return "Not specified"
        return f"${min_sal:,} - ${max_sal:,}"

    @classmethod
    def from_dict(cls, job: dict, company: uuid.UUID) -> "Job":
        """
        Convert a raw job dictionary into a Job instance.
        Requires a resolved company UUID (look it up before calling this).
        """
        salary_range = job.get("salary_range")
        pay_range = (
            [salary_range[0], salary_range[1]]
            if isinstance(salary_range, (tuple, list)) and len(salary_range) == 2
            else None
        )

        return cls(
            title=job.get("title", ""),
            company=company,
            location=job.get("location", "Unknown"),
            is_remote=job.get("is_remote", None),
            description=job.get("description", ""),
            apply_url=job.get("link") or job.get("apply_url"),
            role_type=job.get("role_type", "other"),
            pay_range=pay_range,
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
            "source": job.source,
            "tags": job.tags,
        }

    @classmethod
    def to_dict_for_db(cls, job: "Job") -> dict:
        """Convert a Job instance into a dict suitable for database insertion."""
        tags = job.tags
        if isinstance(tags, list):
            tags = {f"tag_{i}": tag for i, tag in enumerate(tags)}
        elif not isinstance(tags, dict):
            tags = {}

        return {
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "is_remote": job.is_remote,
            "description": job.description,
            "apply_url": job.apply_url,
            "role_type": job.role_type,
            "pay_range": job.pay_range,
            "source": job.source,
            "tags": tags,
            "identifier": job.__hash__(),
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
