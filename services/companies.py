from dataclasses import dataclass
import requests
@dataclass
class Company:
    """
    The company class is used to store information about a company.
    It includes methods to get company information, check if the company is sponsored, get the industry, and perform a fuzzy match with another company.
    The idea is to make the jobs with the same companies use the same name and location, which can help in reducing the number of unique job postings.
    """
    name: str
    location: str
    industry: int
    sponsorships: bool
    company_url: str

    def __post__init__(self):
        if self.name == None or self.location == None or self.industry == None or self.sponsorships == None:
            raise ValueError("Company information is incomplete")
        response = requests.get(self.company_url)
        if response.status_code != 200:
            raise ValueError("Company URL is not reachable")

        #verify the company information from the URL
        if response.json()['name'] != self.name or response.json()['location'] != self.location or response.json()['industry'] != self.industry:
            raise ValueError("Company information from URL does not match the provided information")
    
    def get_company_info(self):
        return f"Company Name: {self.name}, Location: {self.location}, Industry: {self.industry}, Sponsorships: {self.sponsorships}"
    
    def get_company_name(self):
        return self.name
    
    def is_sponsored(self):
        return self.sponsorships
    
    def get_industry(self):
        return self.industry
    
    def fuzzy_match(self, other_company):
        if self.name == other_company.name and self.location == other_company.location and self.industry == other_company.industry:
            return True
        else:
            return False
        
    def is_valid(self):
        return self.name != None and self.location != None and self.industry != None and self.sponsorships != None
        

@dataclass
class Job:
    """
    The Job class is used to store information about a job posting.
    It includes methods to get job information, check if the job is remote, and perform a fuzzy match with another job.
    The idea is to make the jobs with the same companies use the same name and location, which can help in reducing the number of unique job postings.
    """
    title: str
    company: Company
    location: str
    is_remote: bool
    description: str
    apply_url: str
    google_link: str
    highlights: dict[str,list[str]]
    role_type: str
    pay_range: int
    
    def get_job_info(self):
        return f"Job Title: {self.title}, Company: {self.company.name}, Location: {self.location}, Is Remote: {self.is_remote}"
    
    def is_remote_job(self):
        return self.is_remote
    
    def is_valid(self):
        return self.title != None and self.company != None and self.location != None and self.description != None and (self.apply_url != None or self.google_link != None) and self.highlights != None and self.role_type != None and self.pay_range != None
    
  

   