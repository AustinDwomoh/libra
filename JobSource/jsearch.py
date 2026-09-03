import asyncio,os,threading
from tqdm import tqdm
from typing import List, Dict, Optional
import requests,json
from Utils.models import Job
from Utils.constants import PositionType,JSearchConfig, SearchQueries,DatePosted, FilePaths, LogMessages, Defaults,Config
from Utils.run_logging import get_logger, logged_section
from JobSource.base import JobSourceBase

logger = get_logger(__name__)


class JSearch(JobSourceBase):
    """Helper class for JSearch API integration via OpenWebNinja

    This class handles all interactions with the JSearch API, including:
    - Building search queries based on position type
    - Making HTTP requests with proper headers and parameters
    - Handling rate limits and retries
    - Processing and mapping API responses to our standard Job format
    """

    def __init__(self):
        super().__init__()
        self.api_key = Config.J_SEARCH_API_KEY
        if not self.api_key:
            raise ValueError("JSearch API key not configured. Set the J_SEARCH_API_KEY environment variable.")

        self.headers = {"X-API-Key": self.api_key}
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
        response = self._fetch(Config.JSEARCH_API_URL, headers=self.headers, params=params)
        self.request_count += 1
        return response

    async def _process_response(self, response: requests.Response, search_query: str) -> List[Job]:
        data = response.json()
        jobs = data.get("data") if data.get("data") is not None else data
        logger.info(LogMessages.jobs_found(len(jobs), search_query))
        self._save_raw_jobs(jobs)
        return await self._map_jobs(jobs)

    def _save_raw_jobs(self, jobs: List[Dict]) -> None:
        """Save raw job data for debugging"""
        try:
            os.makedirs(os.path.dirname(FilePaths.JSEARCH_RAW_JOBS), exist_ok=True)
            with open(FilePaths.JSEARCH_RAW_JOBS, "w", encoding="utf-8") as f:
                json.dump(jobs, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.warning(f"Could not save raw JSearch jobs: {e}")

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

    async def _map_job(self, job: Dict) -> Job:
        """Map JSearch response to standard job format"""
        company = await self._upsert_company(
            job.get("employer_name") or "unknown",
            company_url=job.get("employer_website"),
        )
       
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
   
        return self._make_job(refined_job, company)

    def _extract_salary(self, job: Dict):
        """Extract salary range from job data"""
        min_sal = job.get("job_min_salary")
        max_sal = job.get("job_max_salary")
        return [min_sal, max_sal] if min_sal and max_sal else None

 

    # ============================================================================ #
    #                                 FETCH FNS                                    #
    # ============================================================================ #

    @logged_section("fetch_jobs")
    async def fetch_jobs(self, queries: Optional[List[str]] = None, position_type: PositionType = PositionType.INTERN, date_posted: DatePosted = DatePosted.WEEK, rate_limit_delay: float = JSearchConfig.RATE_LIMIT_DELAY) -> List[Job]:
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

        for i, query in enumerate(queries):
            logger.info(f"JSearch: Query {i + 1}/{len(queries)}")
            jobs = await self.fetch_positions(query, position_type=position_type, date_posted=date_posted)
            all_jobs.extend(jobs)

            if i < len(queries) - 1:
                logger.debug(f"JSearch: Waiting {rate_limit_delay}s...")
                await asyncio.sleep(rate_limit_delay)
        logger.info(f"JSearch: {len(all_jobs)} jobs before deduplication")

        unique_jobs = list(set(all_jobs))  # Rely on Job's __hash__ and __eq__ for deduplication
        logger.info(f"JSearch: {len(unique_jobs)} unique positions fetched")
        return unique_jobs

    async def fetch_positions(self, query: str = "", position_type: PositionType = PositionType.INTERN, page: int = 1, date_posted: DatePosted = DatePosted.WEEK, retry_count: int = JSearchConfig.DEFAULT_RETRY_COUNT) -> List[Job]:
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
        logger.info(
            f"JSearch: Fetching {position_type} results for '{search_query}' (posted: {date_posted.value})"
        )

        params = self._build_request_params(search_query, position_type, page, date_posted)
        stop_ticker = threading.Event()
        with tqdm(total=retry_count, desc="Jsearch Finding Jobs", unit="job", ncols=100) as pbar:
            ticker = threading.Thread(
                target=lambda: [
                    pbar.refresh() for _ in iter(lambda: stop_ticker.wait(1), True)
                ],
                daemon=True,
            )
            ticker.start()
            try:
                for attempt in range(retry_count):
                    try:
                        response = self._make_request(params)

                        if response.status_code in (401, 403):
                            logger.error(f"JSearch: {response.status_code} - check your API key")
                            return []

                        if response.status_code == 429:
                            wait_time = (attempt + 1) * JSearchConfig.RATE_LIMIT_WAIT_MULTIPLIER
                            logger.warning(f"JSearch: Rate limited. Waiting {wait_time}s (attempt {attempt + 1}/{retry_count})")
                            await asyncio.sleep(wait_time)
                            continue

                        response.raise_for_status()
                        return await self._process_response(response, search_query)

                    except requests.RequestException as e:
                        logger.error(f"JSearch API error: {e}")
                        if attempt < retry_count - 1:
                            await asyncio.sleep(JSearchConfig.RETRY_DELAY)
                            continue
                        return []
                    finally:
                        pbar.update(1)
            finally:
                stop_ticker.set()
                ticker.join(timeout=1)

        logger.error(f"JSearch: All {retry_count} retry attempts failed")
        return []


async def main():
    jsearch_helper = JSearch()
    jobs = await jsearch_helper.fetch_jobs( position_type=PositionType.INTERN, date_posted=DatePosted.WEEK )
    jobs = [Job.to_dict(job) for job in jobs]
    print(f"Total unique jobs fetched: {len(jobs)}")
    with open(FilePaths.JSEARCH_JOBS, 'w', encoding='utf-8') as f:
        json.dump(jobs, f, ensure_ascii=False, indent=4)
    logger.info(f"Total jobs fetched: {len(jobs)}")

if __name__ == "__main__":
    asyncio.run(main())