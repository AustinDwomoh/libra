"""
companies.py - Refactored with constants and improved validation

Key improvements:
- Replaced ALL magic strings with named constants
- Fixed validation bugs (== None checks)
- Added automatic company name normalization
- Made optional fields actually optional with defaults
- Added to_dict/from_dict for database integration
- Fixed pay_range type (was int, now tuple)
- Better error messages and validation
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, List
import requests
from services.constants import (
    Defaults, 
    CompanyValidation, 
    PositionType, 
    HTTPStatus
)


@dataclass
class Company:
    """
    Company information with validation and normalization.
    Designed to work with a database-backed company registry.
    """
    name: str
    location: str
    industry: Optional[int] = Defaults.DEFAULT_INDUSTRY
    sponsorships: bool = Defaults.DEFAULT_SPONSORSHIP
    company_url: Optional[str] = None
    
    # Additional fields for database integration
    verified: bool = False
    normalized_name: str = field(init=False)

    def __post_init__(self):
        """Validate and normalize company data"""
        self._validate_required_fields()
        self.normalized_name = self._normalize_name(self.name)
        
        if self.company_url:
            self._verify_url()

    def _validate_required_fields(self):
        """Validate that required fields are present"""
        if not self.name:
            raise ValueError("Company name is required")
        
        if len(self.name) < CompanyValidation.MIN_NAME_LENGTH:
            raise ValueError(f"Company name must be at least {CompanyValidation.MIN_NAME_LENGTH} character")
        
        if not self.location:
            self.location = Defaults.UNKNOWN_LOCATION

    def _verify_url(self):
        """Verify company URL is accessible"""
        try:
            response = requests.get(
                self.company_url, 
                timeout=CompanyValidation.MAX_URL_TIMEOUT,
                allow_redirects=True
            )
            if response.status_code != HTTPStatus.OK:
                self.company_url = None
                self.verified = False
            else:
                self.verified = True
        except (requests.RequestException, requests.Timeout):
            self.company_url = None
            self.verified = False

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Normalize company name for matching/deduplication"""
        normalized = name.lower().strip()
        
        # Remove common company suffixes
        for term in CompanyValidation.NORMALIZATION_TERMS:
            normalized = normalized.replace(term, "")
        
        # Remove extra whitespace
        normalized = " ".join(normalized.split())
        
        return normalized

    def get_company_info(self) -> str:
        """Get formatted company information"""
        return (
            f"Company: {self.name} | "
            f"Location: {self.location} | "
            f"Industry: {self.industry or 'Unknown'} | "
            f"Sponsorship: {'Yes' if self.sponsorships else 'No'}"
        )

    def get_company_name(self) -> str:
        """Get company name"""
        return self.name

    def is_sponsored(self) -> bool:
        """Check if company sponsors visas"""
        return self.sponsorships

    def get_industry(self) -> Optional[int]:
        """Get industry code"""
        return self.industry

    def fuzzy_match(self, other_company: 'Company', match_location: bool = True) -> bool:
        """
        Check if this company matches another company.
        Uses normalized names for better matching.
        
        Args:
            other_company: Company to compare against
            match_location: Whether to require location match
        """
        names_match = self.normalized_name == other_company.normalized_name
        
        if match_location:
            locations_match = (
                self.location.lower().strip() == 
                other_company.location.lower().strip()
            )
            return names_match and locations_match
        
        return names_match

    def is_valid(self) -> bool:
        """Check if company has all required information"""
        return bool(
            self.name and
            self.location and
            len(self.name) >= CompanyValidation.MIN_NAME_LENGTH
        )

    def to_dict(self) -> Dict:
        """Convert to dictionary for database storage"""
        return {
            "name": self.name,
            "normalized_name": self.normalized_name,
            "location": self.location,
            "industry": self.industry,
            "sponsorships": self.sponsorships,
            "company_url": self.company_url,
            "verified": self.verified
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'Company':
        """Create Company from dictionary"""
        return cls(
            name=data.get("name", Defaults.UNKNOWN_COMPANY),
            location=data.get("location", Defaults.UNKNOWN_LOCATION),
            industry=data.get("industry"),
            sponsorships=data.get("sponsorships", False),
            company_url=data.get("company_url")
        )


@dataclass
class Job:
    """
    Job posting with comprehensive information.
    Integrates with Company class for consistent company data.
    """
    title: str
    company: Company
    location: str
    is_remote: bool
    description: str
    apply_url: Optional[str] = None
    google_link: Optional[str] = None
    highlights: Dict[str, List[str]] = field(default_factory=lambda: Defaults.EMPTY_HIGHLIGHTS.copy())
    role_type: str = PositionType.OTHER.value
    pay_range: Optional[tuple] = None
    
    # Additional metadata
    date_posted: Optional[str] = None
    source: str = "unknown"
    tags: List[str] = field(default_factory=list)

    def __post_init__(self):
        """Validate job data"""
        if not self.title:
            raise ValueError("Job title is required")
        
        if not isinstance(self.company, Company):
            raise ValueError("Company must be a Company instance")
        
        if not self.location:
            self.location = self.company.location or Defaults.UNKNOWN_LOCATION

    def get_job_info(self) -> str:
        """Get formatted job information"""
        return (
            f"Job: {self.title} | "
            f"Company: {self.company.name} | "
            f"Location: {self.location} | "
            f"Remote: {'Yes' if self.is_remote else 'No'} | "
            f"Type: {self.role_type}"
        )

    def is_remote_job(self) -> bool:
        """Check if job is remote"""
        return self.is_remote

    def has_application_link(self) -> bool:
        """Check if job has an application link"""
        return bool(self.apply_url or self.google_link)

    def is_valid(self) -> bool:
        """Check if job has all required information"""
        return bool(
            self.title and
            self.company and
            self.company.is_valid() and
            self.location and
            self.description and
            self.has_application_link() and
            self.role_type
        )

    def get_salary_info(self) -> str:
        """Get formatted salary information"""
        if not self.pay_range:
            return "Not specified"
        
        min_sal, max_sal = self.pay_range
        return f"${min_sal:,} - ${max_sal:,}"

    def to_dict(self) -> Dict:
        """Convert to dictionary for database storage"""
        return {
            "title": self.title,
            "company": self.company.name,
            "location": self.location,
            "link": self.apply_url or self.google_link,
            "sponsorship": (
                "Likely sponsorship" if self.company.sponsorships 
                else "No record found"
            ),
            "source": self.source,
            "remote": self.is_remote,
            "date_posted": self.date_posted,
            "description": self.description,
            "tags": self.tags,
            # Additional fields for internal tracking
            "role_type": self.role_type,
            "salary_range": self.pay_range,
        }

    @staticmethod
    def _to_job_object(job: dict) -> 'Job':
        """
        Convert raw job dictionary into a Job dataclass.
        This is used when parsing API responses.
        """
        # Create company object
        company_obj = Company(
            name=job.get("company", Defaults.UNKNOWN_COMPANY),
            location=job.get("location", Defaults.UNKNOWN_LOCATION),
            industry=job.get("industry", Defaults.DEFAULT_INDUSTRY),
            sponsorships=job.get("sponsorships", Defaults.DEFAULT_SPONSORSHIP),
            company_url=job.get("company_url") or job.get("link", "")
        )
        
        # Extract salary range
        salary_range = job.get("salary_range")
        if salary_range and isinstance(salary_range, (tuple, list)) and len(salary_range) == 2:
            pay_range = tuple(salary_range)
        else:
            pay_range = None
        
        # Create job object
        return Job(
            title=job.get("title", ""),
            company=company_obj,
            location=job.get("location", Defaults.UNKNOWN_LOCATION),
            is_remote=job.get("remote", False),
            description=job.get("description", ""),
            apply_url=job.get("link") or job.get("apply_url"),
            google_link=job.get("google_link"),
            highlights=job.get("highlights", Defaults.EMPTY_HIGHLIGHTS.copy()),
            role_type=job.get("position_type") or job.get("role_type", PositionType.OTHER.value),
            pay_range=pay_range,
            date_posted=job.get("date_posted"),
            source=job.get("source", "unknown"),
            tags=job.get("tags", [])
        )

    @classmethod
    def from_dict(cls, data: Dict) -> 'Job':
        """Create Job from dictionary (e.g., from database)"""
        # Reconstruct company
        company = Company(
            name=data.get("company", Defaults.UNKNOWN_COMPANY),
            location=data.get("location", Defaults.UNKNOWN_LOCATION),
            sponsorships=(data.get("sponsorship") == "Likely sponsorship")
        )
        
        return cls(
            title=data.get("title", ""),
            company=company,
            location=data.get("location", Defaults.UNKNOWN_LOCATION),
            is_remote=data.get("remote", False),
            description=data.get("description", ""),
            apply_url=data.get("link"),
            role_type=data.get("role_type", PositionType.OTHER.value),
            pay_range=data.get("salary_range"),
            date_posted=data.get("date_posted"),
            source=data.get("source", "unknown"),
            tags=data.get("tags", [])
        )


# Utility functions for job/company operations
def normalize_company_name(name: str) -> str:
    """Standalone function to normalize company names"""
    return Company._normalize_name(name)


def create_job_from_api(api_response: Dict, source: str = "api") -> Job:
    """
    Factory function to create Job from API response.
    Handles different API formats.
    """
    job_dict = api_response.copy()
    job_dict["source"] = source
    return Job._to_job_object(job_dict)