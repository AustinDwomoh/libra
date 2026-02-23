"""
jsearch.py - Refactored with constants
"""
from typing import List, Dict
import requests
import time
import json
from services.companies import Job
from services.config import Config
from services.constants import (
    PositionType, DatePosted,
    JSearchConfig, HTTPStatus, SearchQueries, FilePaths, LogMessages, Defaults
)

logger = Config.logger


class JSearchHelper:
    """Helper class for JSearch API integration via OpenWebNinja"""

    def __init__(self):
        self.api_key = Config.J_SEARCH_API_KEY
        if not self.api_key:
            logger.warning("JSearch API key not found in environment variables")

        self.headers = {"X-API-Key": self.api_key}
        self.seen_jobs = set()
        self.request_count = 0

    def fetch_positions(
        self,
        query: str = "",
        position_type: str = PositionType.INTERN.value,
        page: int = 1,
        date_posted: str = DatePosted.WEEK.value,
        retry_count: int = JSearchConfig.DEFAULT_RETRY_COUNT,
    ) -> List[Dict]:
        """Fetch positions from OpenWebNinja JSearch API"""

        if not self.api_key:
            logger.error("JSearch: Cannot make request - API key not configured")
            return []

        search_query = self._build_search_query(query, position_type)
        logger.info(
            f"JSearch: Fetching {position_type} results for '{search_query}' (posted: {date_posted})"
        )

        params = self._build_request_params(search_query, position_type, page, date_posted)

        for attempt in range(retry_count):
            try:
                response = self._make_request(params)
                
                if not self._handle_response_status(response, attempt, retry_count):
                    continue

                jobs = self._process_response(response, position_type, search_query)
                return jobs

            except requests.RequestException as e:
                logger.error(f"JSearch API error: {e}")
                if attempt < retry_count - 1:
                    time.sleep(JSearchConfig.RETRY_DELAY)
                    continue
                return []

        logger.error(f"JSearch: All {retry_count} retry attempts failed")
        return []

    def _build_search_query(self, query: str, position_type: str) -> str:
        """Build search query based on position type"""
        if position_type == PositionType.INTERN.value:
            return f"{query} {SearchQueries.INTERN_SUFFIX}" if query else SearchQueries.INTERN_SUFFIX
        elif position_type == PositionType.FULLTIME.value:
            return f"{query} {SearchQueries.FULLTIME_SUFFIX}" if query else SearchQueries.FULLTIME_SUFFIX
        else:
            return query if query else SearchQueries.DEFAULT_QUERY

    def _build_request_params(
        self, 
        search_query: str, 
        position_type: str, 
        page: int, 
        date_posted: str
    ) -> Dict:
        """Build request parameters"""
        params = {
            "query": search_query,
            "page": page,
            "num_pages": JSearchConfig.DEFAULT_NUM_PAGES,
            "date_posted": date_posted,
        }

        if position_type == PositionType.INTERN.value:
            params["employment_types"] = PositionType.INTERN.value
        elif position_type == PositionType.FULLTIME.value:
            params["employment_types"] = PositionType.FULLTIME.value

        return params

    def _make_request(self, params: Dict) -> requests.Response:
        """Make HTTP request to JSearch API"""
        response = requests.get(
            Config.JSEARCH_API_URL,
            headers=self.headers,
            params=params,
            timeout=Config.REQUEST_TIMEOUT,
        )
        self.request_count += 1
        return response

    def _handle_response_status(
        self, 
        response: requests.Response, 
        attempt: int, 
        retry_count: int
    ) -> bool:
        """Handle HTTP response status codes. Returns True if should continue processing."""
        if response.status_code == HTTPStatus.FORBIDDEN:
            logger.error("JSearch: 403 Forbidden - Check your API key")
            return False

        elif response.status_code == HTTPStatus.UNAUTHORIZED:
            logger.error("JSearch: 401 Unauthorized - Invalid API key")
            return False

        elif response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
            wait_time = (attempt + 1) * JSearchConfig.RATE_LIMIT_WAIT_MULTIPLIER
            logger.warning(
                f"JSearch: Rate limit hit. Waiting {wait_time}s (attempt {attempt + 1}/{retry_count})"
            )
            time.sleep(wait_time)
            return False

        response.raise_for_status()
        return True

    def _process_response(
        self, 
        response: requests.Response, 
        position_type: str, 
        search_query: str
    ) -> List[Dict]:
        """Process API response and filter jobs"""
        data = response.json()
        jobs = data.get("data", [])
        
        logger.debug(f"Jobs found: {len(jobs)}")
        self._save_raw_jobs(jobs)

        filtered_jobs = self._filter_by_employment_type(jobs, position_type)
        logger.info(LogMessages.jobs_found(len(filtered_jobs), search_query))
        
        return [self._map_job(job) for job in filtered_jobs]

    def _save_raw_jobs(self, jobs: List[Dict]):
        """Save raw job data for debugging"""
        with open(FilePaths.JSEARCH_RAW_JOBS, "w", encoding="utf-8") as f:
            json.dump(jobs, f, ensure_ascii=False, indent=4)

    def _filter_by_employment_type(self, jobs: List[Dict], position_type: str) -> List[Dict]:
        """Filter jobs by employment type"""
        filtered_jobs = []
        
        for job in jobs:
            employment_types = job.get("job_employment_types", [])
            
            if self._matches_position_type(employment_types, position_type):
                filtered_jobs.append(job)
        
        return filtered_jobs

    def _matches_position_type(self, employment_types: List[str], position_type: str) -> bool:
        """Check if employment types match the requested position type"""
        if position_type == PositionType.HYBRID.value:
            return (PositionType.INTERN.value in employment_types or 
                    PositionType.FULLTIME.value in employment_types)
        elif position_type == PositionType.INTERN.value:
            return PositionType.INTERN.value in employment_types
        elif position_type == PositionType.FULLTIME.value:
            return PositionType.FULLTIME.value in employment_types
        return False

    def _map_job(self, job: Dict) -> Dict:
        """Map JSearch response to standard job format"""
        employment_types = job.get("job_employment_types", [])
        
        job["position_type"] = self._determine_position_type(employment_types)
        job["location"] = self._get_location(job)
        job["salary_range"] = self._extract_salary(job)
        
        return Job._to_job_object(job)

    def _determine_position_type(self, employment_types: List[str]) -> str:
        """Determine position type from employment types"""
        has_intern = PositionType.INTERN.value in employment_types
        has_fulltime = PositionType.FULLTIME.value in employment_types
        
        if has_intern and has_fulltime:
            return PositionType.HYBRID.value
        elif has_intern:
            return PositionType.INTERN.value
        elif has_fulltime:
            return PositionType.FULLTIME.value
        else:
            return PositionType.OTHER.value

    def _extract_salary(self, job: Dict):
        """Extract salary range from job data"""
        min_sal = job.get("job_min_salary")
        max_sal = job.get("job_max_salary")

        if min_sal and max_sal:
            return (min_sal, max_sal)
        return None

    def _get_location(self, job: Dict) -> str:
        """Extract location from JSearch job"""
        city = job.get("job_city", "")
        state = job.get("job_state", "")
        country = job.get("job_country", "")

        parts = [p for p in [city, state, country] if p]
        return ", ".join(parts) if parts else Defaults.LOCATION_NOT_SPECIFIED

    def _deduplicate_jobs(self, jobs: List[Dict]) -> List[Dict]:
        """Remove duplicate jobs based on job_id"""
        unique_jobs = []

        for job in jobs:
            job_id = job.get("job_id")
            if job_id and job_id not in self.seen_jobs:
                self.seen_jobs.add(job_id)
                unique_jobs.append(job)

        return unique_jobs

    def fetch_jobs(
        self,
        categories: List[str] = None,
        custom_queries: List[str] = None,
        position_type: str = PositionType.INTERN.value,
        date_posted: str = DatePosted.WEEK.value,
        rate_limit_delay: float = JSearchConfig.RATE_LIMIT_DELAY,
    ) -> List[Dict]:
        """Main method: Fetch jobs with rate limiting"""

        if not self.api_key:
            logger.error("JSearch: Cannot fetch jobs - API key not configured")
            return []

        queries = self._determine_queries(categories, custom_queries)
        all_jobs = []
        self.seen_jobs.clear()

        for i, query in enumerate(queries):
            logger.info(f"JSearch: Query {i+1}/{len(queries)}")

            jobs = self.fetch_positions(
                query, 
                position_type=position_type, 
                date_posted=date_posted
            )
            all_jobs.extend(jobs)

            if i < len(queries) - 1:
                logger.debug(f"JSearch: Waiting {rate_limit_delay}s...")
                time.sleep(rate_limit_delay)

        unique_jobs = self._deduplicate_jobs(all_jobs)
        logger.info(f"JSearch: {len(unique_jobs)} unique positions fetched")
        
        return unique_jobs

    def _determine_queries(
        self, 
        categories: List[str] = None, 
        custom_queries: List[str] = None
    ) -> List[str]:
        """Determine which queries to use"""
        if custom_queries:
            return custom_queries
        elif categories:
            return categories
        else:
            return JSearchConfig.DEFAULT_CATEGORIES

    def fetch_jobs_for_student(
        self,
        student_major: str,
        position_type: str = PositionType.INTERN.value,
        include_general: bool = True,
    ) -> List[Dict]:
        """Fetch jobs tailored to a specific student's major"""
        queries = [student_major]

        if include_general:
            queries.extend(self._get_general_queries(position_type))

        return self.fetch_jobs(custom_queries=queries, position_type=position_type)

    def _get_general_queries(self, position_type: str) -> List[str]:
        """Get general queries based on position type"""
        if position_type == PositionType.INTERN.value:
            return [SearchQueries.INTERN_SUFFIX]
        elif position_type == PositionType.FULLTIME.value:
            return [SearchQueries.FULLTIME_SUFFIX]
        elif position_type == PositionType.PARTTIME.value:
            return [SearchQueries.PARTTIME_SUFFIX]
        elif position_type == PositionType.REMOTE.value:
            return [SearchQueries.REMOTE_SUFFIX]
        else:
            return [SearchQueries.INTERN_SUFFIX, SearchQueries.FULLTIME_SUFFIX]

def main():
    jsearch_helper = JSearchHelper()
    jobs = jsearch_helper.fetch_jobs(
        position_type=PositionType.INTERN.value,
        date_posted=DatePosted.WEEK.value
    )
    with open('jsearch_jobs.json', 'w', encoding='utf-8') as f:
        json.dump(jobs, f, ensure_ascii=False, indent=4)
    logger.info(f"Total jobs fetched: {len(jobs)}")

if __name__ == "__main__":
    main()