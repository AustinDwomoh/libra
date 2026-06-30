import json

from Utils.constants import Config, LLMConstants
from Utils.models import Job


class JobDataSanitizer:
    """Sanitizes job data before sending to LLM for enrichment, and cleans
    raw LLM JSON output before it touches the Job/DB."""

    def _build_prompt(self, job: Job, text: str) -> str:
        known = {
            "title":     job.title     if not Config.is_missing(job.title)     else None,
            "location":  job.location  if not Config.is_missing(job.location)  else None,
            "is_remote": job.is_remote if not Config.is_missing(job.is_remote) else None,
            "role_type": job.role_type if not Config.is_missing(job.role_type) else None,
            "pay_range": job.pay_range if not Config.is_missing(job.pay_range) else None,
        }
        return LLMConstants._LLM_PROMPT.format(
            known=json.dumps({k: v for k, v in known.items() if v is not None}, indent=2),
            text=text[:LLMConstants._MAX_PROMPT_CHARS],
        )

    def _normalise_pay(self, data: dict) -> dict:
        """Ensure pay_range is always [min, max] format with numeric (or None) values."""
        if "pay_range" in data and data["pay_range"] is not None:
            pr = data["pay_range"]
            if isinstance(pr, list) and len(pr) >= 1:
                lo = pr[0] if len(pr) >= 1 else None
                hi = pr[1] if len(pr) >= 2 else None
                lo = lo if isinstance(lo, (int, float)) and lo >= 0 else None
                hi = hi if isinstance(hi, (int, float)) and hi >= 0 else None
                if lo is None and hi is None:
                    data["pay_range"] = None
                else:
                    if lo is not None and hi is not None and lo > hi:
                        lo, hi = hi, lo
                    data["pay_range"] = [lo, hi]
            else:
                data["pay_range"] = None
        return data

    def _normalise_role_type(self, data: dict) -> dict:
        """Coerce role_type into one of the canonical enum values."""
        if "role_type" not in data:
            return data
        value = data["role_type"]
        if value is None:
            return data
        if not isinstance(value, str):
            data["role_type"] = "other"
            return data
        lowered = value.strip().lower()
        if lowered in LLMConstants._VALID_ROLE_TYPES:
            data["role_type"] = lowered
            return data
        for pattern, canonical in LLMConstants._ROLE_TYPE_KEYWORDS:
            if pattern.search(value):
                data["role_type"] = canonical
                return data
        data["role_type"] = "other"
        return data

    def _normalise_is_remote(self, data: dict) -> dict:
        """Coerce is_remote into True/False/None; drop anything else."""
        if "is_remote" not in data:
            return data
        value = data["is_remote"]
        if isinstance(value, bool) or value is None:
            return data
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in ("true", "yes", "remote"):
                data["is_remote"] = True
                return data
            if lowered in ("false", "no", "onsite", "on-site", "hybrid"):
                data["is_remote"] = False
                return data
        data["is_remote"] = None
        return data

    def _normalise_job_expired(self, data: dict) -> dict:
        """Coerce job_expired into a strict bool, defaulting to False."""
        if "job_expired" not in data:
            return data
        value = data["job_expired"]
        if isinstance(value, bool):
            return data
        if isinstance(value, str) and value.strip().lower() in ("true", "yes"):
            data["job_expired"] = True
            return data
        data["job_expired"] = False
        return data

    def _normalise_tags(self, data: dict) -> dict:
        """Ensure tags is a flat dict[str, str], dropping malformed entries."""
        if "tags" not in data:
            return data
        value = data["tags"]
        if not isinstance(value, dict):
            data["tags"] = None
            return data
        cleaned = {}
        for k, v in value.items():
            if not isinstance(k, str):
                continue
            if v is None:
                continue
            if not isinstance(v, str):
                v = str(v)
            v = v.strip()
            if not v:
                continue
            cleaned[k] = v[:100]
            if len(cleaned) >= LLMConstants._MAX_TAGS:
                break
        data["tags"] = cleaned or None
        return data

    def _normalise_text_fields(self, data: dict) -> dict:
        """Ensure free-text fields are actually strings (or None), within sane length limits."""
        for field_name, limit in LLMConstants._TEXT_FIELD_LIMITS.items():
            if field_name not in data:
                continue
            value = data[field_name]
            if value is None:
                continue
            if not isinstance(value, str):
                data[field_name] = None
                continue
            value = value.strip()
            data[field_name] = value[:limit] if value else None
        return data

    def sanitize(self, data: dict) -> dict:
        """Run all field-level sanitizers over raw LLM JSON before it touches the Job/DB."""
        if not isinstance(data, dict):
            return {}
        data = self._normalise_pay(data)
        data = self._normalise_role_type(data)
        data = self._normalise_is_remote(data)
        data = self._normalise_job_expired(data)
        data = self._normalise_tags(data)
        data = self._normalise_text_fields(data)
        return data