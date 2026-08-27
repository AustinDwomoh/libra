```mermaid
%% classDiagram — constants.py: all config and enum classes
classDiagram
    class Config {
        +FUZZY_THRESHOLD: int
        +REQUEST_TIMEOUT: int
        +JSEARCH_API_URL: str
        +J_SEARCH_API_KEY: str
        +GROQ_API_KEY: str
        +GEMINI_KEY: str
        +DB_HOST: str
        +DB_PORT: int
        +DB_NAME: str
        +DB_USER: str
        +DB_PASSWORD: str
        +DISCORD_WEBHOOK: str
        +DISCLAIMER_TEXT: str
        -file_handler: FileHandler
        +logger: Logger
        +save_to_json(jobs, filepath)$
        +strip_html(text) str$
        +clean_ws(text) str$
        +is_missing(value) bool$
        +_norm_amount(s) float$
    }

    class LLMConstants {
        <<constants>>
        +_LLM_PROMPT: str
        +_MAX_PROMPT_CHARS: int
        +_VALID_ROLE_TYPES: set
        +_ROLE_TYPE_KEYWORDS: list
        +_TEXT_FIELD_LIMITS: dict
    }

    class PositionType {
        <<enum>>
        INTERN
        FULLTIME
        PARTIME
        REMOTE
        HYBRID
        OTHER
    }

    class JobSource {
        <<enum>>
        SIMPLIFY
        JSEARCH
        SPEEDY
    }

    class DatePosted {
        <<enum>>
        ALL
        TODAY
        THREE_DAYS
        WEEK
        MONTH
    }

    class JSearchConfig {
        <<constants>>
        +DEFAULT_CATEGORIES: list
        +DEFAULT_NUM_PAGES: str
        +DEFAULT_RETRY_COUNT: int
        +RATE_LIMIT_WAIT_MULTIPLIER: int
        +RATE_LIMIT_DELAY: float
        +RETRY_DELAY: int
    }

    class SimplifyConfig {
        <<constants>>
        +CONTINUATION_MARKER: str
        +MIN_TABLE_COLUMNS: int
        +EXCLUDED_LINK_PREFIXES: list
        +EXCLUDED_LINK_DOMAINS: list
        +DEFAULT_URL: str
    }

    class SpeedyConfig {
        <<constants>>
        +DEFAULT_URL: str
        +MIN_TABLE_COLUMNS: int
        +MAX_JOB_AGE_DAYS: int
        +EXCLUDED_LINK_PREFIXES: list
        +EXCLUDED_LINK_DOMAINS: list
    }

    class SearchQueries {
        <<constants>>
        +INTERN_SUFFIX: str
        +FULLTIME_SUFFIX: str
        +PARTTIME_SUFFIX: str
        +REMOTE_SUFFIX: str
        +DEFAULT_QUERY: str
    }

    class FilePaths {
        <<constants>>
        +SCRAPED_JOBS_JSON: str
        +JSEARCH_RAW_JOBS: str
        +JSEARCH_JOBS: str
        +LAST_RUN: str
    }

    class Defaults {
        <<constants>>
        +UNKNOWN_COMPANY: str
        +UNKNOWN_LOCATION: str
        +LOCATION_NOT_SPECIFIED: str
        +EMPTY_HIGHLIGHTS: dict
        +DEFAULT_SPONSORSHIP: bool
    }

    class LogMessages {
        <<static methods>>
        +fetch_start(source, position_type, date_posted) str$
        +jobs_found(count, query) str$
        +deduplication_result(original, unique) str$
        +sponsorship_tagged(tagged, total) str$
        +bulk_insert_complete(count) str$
    }

    class StatsKeys {
        <<constants>>
        +SIMPLIFY: str
        +JSEARCH: str
        +TOTAL_FETCHED: str
        +UNIQUE_JOBS: str
        +INSERTED: str
        +ERRORS: str
        +POSITION_TYPE: str
    }

    class JSearchConfig
    class HTTPStatus {
        <<constants>>
        +OK: int
        +UNAUTHORIZED: int
        +FORBIDDEN: int
        +TOO_MANY_REQUESTS: int
    }

    class FuzzyMatchConfig {
        <<constants>>
        +DEFAULT_THRESHOLD: int
        +NORMALIZATION_REMOVE: list
    }

    class JobValidation {
        <<constants>>
        +MIN_TITLE_LENGTH: int
        +MIN_COMPANY_LENGTH: int
        +EXCLUDED_DOMAINS: list
        +CONTINUATION_MARKER: str
    }

    Config --> FilePaths : save_to_json default path
    Config --> LLMConstants : logging config shared by same module
    SpeedyConfig --> SimplifyConfig : reuses EXCLUDED_LINK_PREFIXES/DOMAINS

    note for Config "Logging now writes to logs/run.log via a\ndedicated file_handler (DEBUG level), in\naddition to the existing basicConfig setup.\n\nis_missing() now also treats the literal\nstrings '{}', '[]', 'null', and 'None' as\nmissing, on top of the prior '', 'Unknown',\n'other', 'unknown' — guards against LLM/DB\nround-trips that stringify empty containers.\n\nThe Simplify README URL now lives on\nSimplifyConfig.DEFAULT_URL instead of Config\n(also bumped Summer2026 -> Summer2027)."

    note for LLMConstants "Prompt schema changed: the old flat\n'description' field is now 'summary'\n(2-4 sentence, own-words) plus a new\n'description_looks_valid' bool. job_expired\nis now specified to never return null (only\ntrue/false). _MAX_TAGS was removed —\ntags are no longer capped at 11 entries.\n_TEXT_FIELD_LIMITS now limits 'summary'\n(500 chars) instead of 'description'.\n\ntags gained a 'sponsorship': true|false|null\nkey (issue #18) — see [[Roadmap]] for why the\n/sponsor route matches the literal string\n'True', not 'true'."

    note for FilePaths "LAST_RUN (resources/last_run.json) is new —\nSimplify and Speedy each stamp their own key\nin it after a successful fetch, used to compute\nhow far back to look on the next run."
```