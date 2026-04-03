"""
jsearch.py - Refactored with constants
"""
import asyncio
from typing import List, Dict
import requests,json,time
from Utils.models import Job
from Utils.constants import PositionType,JSearchConfig, HTTPStatus, SearchQueries,DatePosted, FilePaths, LogMessages, Defaults,Config
from Service.db import JobDatabase



class JSearch:
    """Helper class for JSearch API integration via OpenWebNinja
    
    This class handles all interactions with the JSearch API, including:
    - Building search queries based on position type
    - Making HTTP requests with proper headers and parameters
    - Handling rate limits and retries
    - Processing and mapping API responses to our standard Job format
    """

    def __init__(self):
        self.api_key = Config.J_SEARCH_API_KEY
        if not self.api_key:
            raise ValueError("JSearch API key not configured. Set the J_SEARCH_API_KEY environment variable.")

        self.headers = {"X-API-Key": self.api_key}
        self.seen_jobs = set()
        self.request_count = 0

    # ============================================================================ #
    #                              QUERY / PARAMS                                  #
    # ============================================================================ #

    def _build_search_query(self, query: str, position_type: PositionType) -> str:
        """Build search query based on position type
        
        This centralizes the logic for how we construct search queries, ensuring consistency across both the query string and the employment_types filter.
        """
        if position_type == PositionType.INTERN:
            return f"{query} {SearchQueries.INTERN_SUFFIX}" if query else SearchQueries.INTERN_SUFFIX
        elif position_type == PositionType.FULLTIME:
            return f"{query} {SearchQueries.FULLTIME_SUFFIX}" if query else SearchQueries.FULLTIME_SUFFIX
        return query if query else SearchQueries.DEFAULT_QUERY

    def _build_request_params( self, search_query: str, position_type: PositionType, page: int, date_posted: DatePosted,) -> Dict:
        """Build request parameters"""
        params = {
            "query": search_query,
            "page": page,
            "num_pages": JSearchConfig.DEFAULT_NUM_PAGES,
            "date_posted": date_posted.value,
        }

        # Only add employment_types for non-hybrid requests; the query suffix already
        # handles the filter so we mirror it here only when unambiguous.
        if position_type in (PositionType.INTERN, PositionType.FULLTIME):
            params["employment_types"] = position_type.value
        return params

    # ============================================================================ #
    #                            HTTP / RESPONSE                                   #
    # ============================================================================ #

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
        retry_count: int,
    ) -> bool:
        """Handle HTTP response status codes. Returns True if processing should continue."""
        if response.status_code == HTTPStatus.FORBIDDEN:
            Config.logger.error("JSearch: 403 Forbidden - Check your API key")
            return False

        if response.status_code == HTTPStatus.UNAUTHORIZED:
            Config.logger.error("JSearch: 401 Unauthorized - Invalid API key")
            return False

        if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
            wait_time = (attempt + 1) * JSearchConfig.RATE_LIMIT_WAIT_MULTIPLIER
            Config.logger.warning(
                f"JSearch: Rate limit hit. Waiting {wait_time}s (attempt {attempt + 1}/{retry_count})"
            )
            time.sleep(wait_time)
            return False

        response.raise_for_status()
        return True

    async def _process_response(
        self,
        response: requests.Response,
        search_query: str,
    ) -> List[Job]:
        """Process API response and filter jobs"""
       
        data = response.json()
        jobs = data.get("data", []) or data
        

        Config.logger.debug(f"Jobs found: {len(jobs)}")
        
        self._save_raw_jobs(jobs)

        Config.logger.info(LogMessages.jobs_found(len(jobs), search_query))

        return [await self._map_job(job) for job in jobs]

    def _save_raw_jobs(self, jobs: List[Dict]) -> None:
        """Save raw job data for debugging"""
        with open(FilePaths.JSEARCH_RAW_JOBS, "w", encoding="utf-8") as f:
            json.dump(jobs, f, ensure_ascii=False, indent=4)

    # ============================================================================ #
    #                          POSITION TYPE HELPERS                               #
    # ============================================================================ #

    def _get_position_type(self, employment_types: List[str]) -> PositionType:
        """
        Derive a single PositionType value from a job's employment_types list.
        This is the single source of truth for position-type logic, used by
        both filtering and mapping.
        """
        has_intern = PositionType.INTERN.value in employment_types
        has_fulltime = PositionType.FULLTIME.value in employment_types

        if has_intern and has_fulltime:
            return PositionType.HYBRID
        if has_intern:
            return PositionType.INTERN
        if has_fulltime:
            return PositionType.FULLTIME
        return PositionType.OTHER

    def _matches_position_type(self, employment_types: List[str], position_type: PositionType) -> bool:
        """Check whether a job's employment types satisfy the requested position type filter."""
        actual = self._get_position_type(employment_types)

        if position_type == PositionType.HYBRID:
            # Hybrid filter accepts intern, fulltime, or hybrid jobs
            return actual in (
                PositionType.INTERN,
                PositionType.FULLTIME,
                PositionType.HYBRID,
            )
        return actual == position_type

    # ============================================================================ #
    #                           FILTERING / MAPPING                                #
    # ============================================================================ #



    async def _map_job(self, job: Dict) -> Job:
        """Map JSearch response to standard job format"""
        compnay_dict = {
            "name": (job.get("employer_name") or "unknown").lower(),
            "company_url": job.get("employer_website")
        }
        DB = await JobDatabase.create()

        company = await DB.upsert(table="company",data = compnay_dict)  # Upsert company and get the record with ID
        if not company:
            company = await DB.selectOne(table="company", filters={"name": compnay_dict["name"]})
       
        employment_types = job.get("job_employment_types", [])
        refined_job = {
            "title": job.get("job_title", "Unknown").lower(),
            "location": job.get("job_location") or Defaults.LOCATION_NOT_SPECIFIED,
            "is_remote": job.get("job_is_remote", False),
            "description": job.get("job_description", ""),
            "apply_url": job.get("job_apply_link") or job.get("job_google_link"),
            "role_type": self._get_position_type(employment_types).value,
            "salary_range": self._extract_salary(job),
            "source": "jsearch",
            "tags": job.get("job_highlights"),
        }
   
        return Job.from_dict(refined_job, company=company.get("id")) #type: ignore might be None but will raise in that case, which is fine

    def _extract_salary(self, job: Dict):
        """Extract salary range from job data"""
        min_sal = job.get("job_min_salary")
        max_sal = job.get("job_max_salary")
        return[min_sal, max_sal] if min_sal and max_sal else None

 

    # ============================================================================ #
    #                                 FETCH FNS                                    #
    # ============================================================================ #

    async def fetch_jobs( self, queries: List[str] = [], position_type: PositionType = PositionType.INTERN, date_posted: DatePosted = DatePosted.WEEK, rate_limit_delay: float = JSearchConfig.RATE_LIMIT_DELAY,) -> List[Job]:
        """
        Fetch jobs across multiple search queries with rate limiting.

        To find all positions for a specific major, pass a list of queries such as
        ["computer science", "data science"] and set include_general=False in
        fetch_jobs_for_student.

        Args:
            queries:           List of search terms. Defaults to JSearchConfig.DEFAULT_CATEGORIES.
            position_type:     One of PositionType values (intern / fulltime / hybrid).
            date_posted:       DatePosted enum controlling recency filter.
            rate_limit_delay:  Seconds to wait between successive query requests.

        Returns:
            Deduplicated list of standardised job dicts.
        """
        queries = queries or JSearchConfig.DEFAULT_CATEGORIES
        all_jobs = []
        self.seen_jobs.clear()

        for i, query in enumerate(queries):
            Config.logger.info(f"JSearch: Query {i + 1}/{len(queries)}")
            jobs = await self.fetch_positions(query, position_type=position_type, date_posted=date_posted)
            all_jobs.extend(jobs)

            if i < len(queries) - 1:
                Config.logger.debug(f"JSearch: Waiting {rate_limit_delay}s...")
                await asyncio.sleep(rate_limit_delay)
        Config.logger.info(f"JSearch: {len(all_jobs)} jobs before deduplication")

        unique_jobs = list(set(all_jobs))  # Rely on Job's __hash__ and __eq__ for deduplication
        Config.logger.info(f"JSearch: {len(unique_jobs)} unique positions fetched")
        return unique_jobs

    async  def fetch_positions( self, query: str = "", position_type: PositionType = PositionType.INTERN, page: int = 1, date_posted: DatePosted = DatePosted.WEEK, retry_count: int = JSearchConfig.DEFAULT_RETRY_COUNT,) -> List[Job]:
        """
        Fetch a single page of positions from the JSearch API.

        Args:
            query:         Raw search term (suffixes are appended automatically).
            position_type: One of PositionType values.
            page:          Page number to request.
            date_posted:   DatePosted enum controlling recency filter.
            retry_count:   Number of retry attempts on transient failures.

        Returns:
            List of Job objects, or [] on failure.
        """
        search_query = self._build_search_query(query, position_type)
        Config.logger.info(
            f"JSearch: Fetching {position_type} results for '{search_query}' (posted: {date_posted.value})"
        )

        params = self._build_request_params(search_query, position_type, page, date_posted)

        for attempt in range(retry_count):
            try:
                response = self._make_request(params)
                
                
                if not self._handle_response_status(response, attempt, retry_count):
                    return []
                
                return await self._process_response(response, search_query)

            except requests.RequestException as e:
                Config.logger.error(f"JSearch API error: {e}")
                if attempt < retry_count - 1:
                    time.sleep(JSearchConfig.RETRY_DELAY)
                    continue
                return []

        Config.logger.error(f"JSearch: All {retry_count} retry attempts failed")
        return []


async def main():
    jsearch_helper = JSearch()
    jobs = await jsearch_helper.fetch_jobs( position_type=PositionType.INTERN, date_posted=DatePosted.WEEK )
    jobs = [job.to_dict(job) for job in jobs]  # Convert Job objects to dicts for JSON serialization
    print(f"Total unique jobs fetched: {len(jobs)}")
    with open(FilePaths.JSEARCH_JOBS, 'w', encoding='utf-8') as f:
        json.dump(jobs, f, ensure_ascii=False, indent=4)
    Config.logger.info(f"Total jobs fetched: {len(jobs)}")

if __name__ == "__main__":
    asyncio.run(main())