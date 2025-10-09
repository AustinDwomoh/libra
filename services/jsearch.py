from typing import List, Dict
import requests, time
from config import Config,logger

class JSearchHelper:
    """Helper class for JSearch API integration via     OpenWebNinja"""
    
    DEFAULT_CATEGORIES = ["software", "data science", "marketing"]
    
    def __init__(self):
        self.api_key = Config.J_SEARCH_API_KEY
        if not self.api_key:
            logger.warning("JSearch API key not found in environment variables")
        
        self.headers = {
            "X-API-Key": self.api_key  # Confirmed working header format
        }
        self.seen_jobs = set()
        self.request_count = 0
    
    def fetch_positions(self, query: str = "", position_type: str = "intern", 
                   page: int = 1, date_posted: str = "week", retry_count: int = 3) -> List[Dict]:
        """
        Fetch positions from OpenWebNinja JSearch API
        
        Args:
            query: Search query (e.g., "software", "marketing")
            position_type: "intern", "fulltime", or "both"
            page: Page number for pagination
            date_posted: "all", "today", "3days", "week", "month"
            retry_count: Number of retries on failure
        """
        
        if not self.api_key:
            logger.error("JSearch: Cannot make request - API key not configured")
            return []
        
        if position_type == "intern":
            search_query = f"{query} intern" if query else "intern"
        elif position_type == "fulltime":
            search_query = f"{query} entry level" if query else "entry level"
        else:
            search_query = query if query else "developer"
        
        logger.info(f"JSearch: Fetching {position_type} results for '{search_query}' (posted: {date_posted})")
        
        params = {
            "query": search_query,
            "page": page,
            "num_pages": "1",
            "date_posted": date_posted  # Add date filter here
        }
        
        if position_type == "intern":
            params["employment_types"] = "INTERN"
        elif position_type == "fulltime":
            params["employment_types"] = "FULLTIME"
        
        for attempt in range(retry_count):
            try:
                response = requests.get(
                    Config.JSEARCH_API_URL,
                    headers=self.headers,
                    params=params,
                    timeout=Config.REQUEST_TIMEOUT
                )
                
                self.request_count += 1
                
                if response.status_code == 403:
                    logger.error("JSearch: 403 Forbidden - Check your API key")
                    return []
                
                elif response.status_code == 401:
                    logger.error("JSearch: 401 Unauthorized - Invalid API key")
                    return []
                
                elif response.status_code == 429:
                    wait_time = (attempt + 1) * 5
                    logger.warning(f"JSearch: Rate limit hit. Waiting {wait_time}s (attempt {attempt + 1}/{retry_count})")
                    time.sleep(wait_time)
                    continue
                
                response.raise_for_status()
                data = response.json()
                jobs = data.get("data", [])
                
                # Filter by employment type
                filtered_jobs = []
                for job in jobs:
                    employment_types = job.get("job_employment_types", [])
                    
                    if position_type == "both":
                        if "INTERN" in employment_types or "FULLTIME" in employment_types:
                            filtered_jobs.append(job)
                    elif position_type == "intern":
                        if "INTERN" in employment_types:
                            filtered_jobs.append(job)
                    elif position_type == "fulltime":
                        if "FULLTIME" in employment_types:
                            filtered_jobs.append(job)
                
                logger.info(f"JSearch: Found {len(filtered_jobs)} positions for '{search_query}'")
                return [self._map_job(job) for job in filtered_jobs]
                
            except requests.RequestException as e:
                logger.error(f"JSearch API error: {e}")
                if attempt < retry_count - 1:
                    time.sleep(2)
                    continue
                return []
        
        logger.error(f"JSearch: All {retry_count} retry attempts failed")
        return []
    
    def _map_job(self, job: Dict) -> Dict:
        """Map JSearch response to standard job format"""
        employment_types = job.get("job_employment_types", [])
        
        if "INTERN" in employment_types and "FULLTIME" in employment_types:
            position_type = "hybrid"
        elif "INTERN" in employment_types:
            position_type = "internship"
        elif "FULLTIME" in employment_types:
            position_type = "fulltime"
        else:
            position_type = "other"
        
        return {
            "job_id": job.get("job_id"),
            "company": job.get("employer_name", ""),
            "title": job.get("job_title", ""),
            "location": self._get_location(job),
            "link": job.get("job_apply_link", ""),
            "source": "jsearch",
            "date_posted": job.get("job_posted_at_datetime_utc"),
            "description": job.get("job_description"),
            "remote": job.get("job_is_remote", False),
            "sponsorship": None,
            "position_type": position_type,
            "employment_types": employment_types,
            "salary_range": self._extract_salary(job),
            "posted_days_ago": job.get("job_posted_at")
        }
    
    def _extract_salary(self, job: Dict) -> str:
        """Extract salary information if available"""
        min_sal = job.get("job_min_salary")
        max_sal = job.get("job_max_salary")
        period = job.get("job_salary_period")
        
        if min_sal and max_sal and period:
            return f"${min_sal:,} - ${max_sal:,} {period}"
        elif job.get("job_salary"):
            return job.get("job_salary")
        return None
    
    def _get_location(self, job: Dict) -> str:
        """Extract location from JSearch job"""
        city = job.get("job_city", "")
        state = job.get("job_state", "")
        country = job.get("job_country", "")
        
        parts = [p for p in [city, state, country] if p]
        return ", ".join(parts) if parts else "Not specified"
    
    def _deduplicate_jobs(self, jobs: List[Dict]) -> List[Dict]:
        """Remove duplicate jobs based on job_id"""
        unique_jobs = []
        
        for job in jobs:
            job_id = job.get("job_id")
            if job_id and job_id not in self.seen_jobs:
                self.seen_jobs.add(job_id)
                unique_jobs.append(job)
        
        return unique_jobs
    
    def fetch_jobs(self, categories: List[str] = None, custom_queries: List[str] = None, 
               position_type: str = "intern", date_posted: str = "week", 
               rate_limit_delay: float = 2.0) -> List[Dict]:
        """
        Main method: Fetch jobs with rate limiting
        
        Args:
            categories: List of job categories
            custom_queries: List of full custom queries
            position_type: "intern", "fulltime", or "both"
            date_posted: "all", "today", "3days", "week", "month"
            rate_limit_delay: Seconds to wait between requests
        """
        
        if not self.api_key:
            logger.error("JSearch: Cannot fetch jobs - API key not configured")
            return []
        
        if custom_queries:
            queries = custom_queries
        elif categories:
            queries = categories
        else:
            queries = self.DEFAULT_CATEGORIES
        
        all_jobs = []
        self.seen_jobs.clear()
        
        for i, query in enumerate(queries):
            logger.info(f"JSearch: Query {i+1}/{len(queries)}")
            
            jobs = self.fetch_positions(query, position_type=position_type, date_posted=date_posted)
            all_jobs.extend(jobs)
            
            if i < len(queries) - 1:
                logger.debug(f"JSearch: Waiting {rate_limit_delay}s...")
                time.sleep(rate_limit_delay)
        
        unique_jobs = self._deduplicate_jobs(all_jobs)
        
        logger.info(f"JSearch: {len(unique_jobs)} unique positions fetched")
        return unique_jobs
    
    def fetch_jobs_for_student(self, student_major: str, position_type: str = "intern", 
                                include_general: bool = True) -> List[Dict]:
        """Fetch jobs tailored to a specific student's major"""
        queries = [student_major]
        
        if include_general:
            if position_type == "intern":
                queries.append("intern")
            elif position_type == "fulltime":
                queries.append("entry level")
            else:
                queries.extend(["intern", "entry level"])
        
        return self.fetch_jobs(custom_queries=queries, position_type=position_type)
   