from abc import ABC, abstractmethod
from typing import Optional
import json, re
#for when we later want to add a local model option:
#import os,torch
#from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline

from Utils.constants import Config
from Utils.run_logging import get_logger
from Utils.models import Job
from Utils.sanitate import JobDataSanitizer

logger = get_logger(__name__)

# ─── Base Class ────────────────────────────────────────────────────────────────

class LLMParseError(Exception):
    """
    Raised when an LLM response can't be parsed as JSON even after repair
    attempts. Distinct from network/rate-limit errors raised by complete():
    callers should treat this as a (likely permanent) bad-output failure
    rather than a transient one worth retrying indefinitely.
    """
    pass


def _try_repair_json(raw: str) -> dict | None:
    """
    Attempt to recover a dict from near-valid JSON. Smaller/local models
     sometimes emit trailing commas, smart
    quotes, single-quoted keys, or stray prose around the JSON block.
    Returns the parsed dict, or None if nothing worked.
    """
    # 1) Prefer the json_repair library if it's installed — handles far more
    #    cases than the regex fixups below. Optional dependency, so degrade
    #    gracefully if it's not available.
    try:
        import json_repair  # type: ignore
        try:
            repaired = json_repair.loads(raw)
            if isinstance(repaired, dict):
                return repaired
        except Exception:
            pass
    except ImportError:
        pass

    candidate = raw

    # 2) Normalize smart/curly quotes to straight quotes.
    candidate = (
        candidate.replace("\u201c", '"').replace("\u201d", '"')
        .replace("\u2018", "'").replace("\u2019", "'")
    )

    # 3) Strip trailing commas before a closing } or ].
    candidate = re.sub(r",\s*([}\]])", r"\1", candidate)

    try:
        result = json.loads(candidate)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # 4) Single-quoted JSON-ish output (only attempt if there are no double
    #    quotes at all, to avoid mangling legitimate apostrophes in strings).
    if "'" in candidate and '"' not in candidate:
        attempt = candidate.replace("'", '"')
        try:
            result = json.loads(attempt)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    # 5) Last resort: pull out the first {...} block in case the model added
    #    leading/trailing prose despite instructions not to.
    match = re.search(r"\{.*\}", candidate, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(0))
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    return None


class LLMProvider(ABC):
    """Base class for LLM providers. Implement `complete(prompt) -> str`."""

    @abstractmethod
    def complete(self, prompt: str) -> str:
        """Send prompt, return raw response text."""
        ...

    def extract(self, job: Job, text: str) -> dict:
        """
        Build prompt, call LLM, parse and return extracted fields.

        Raises:
            Whatever complete() raises (network/API/rate-limit errors) —
            these are transient and callers should retry without penalty.
            LLMParseError — the response couldn't be parsed as JSON even
            after repair attempts. Callers should treat repeated occurrences
            of this as a likely-permanent failure (bad model output for this
            job) rather than retrying forever.
        """
        prompt = JobDataSanitizer()._build_prompt(job, text)
        # Let completion-level exceptions (network, auth, rate limit) bubble
        # up unmodified — those are transient and shouldn't be conflated
        # with a parse failure.
        raw = self.complete(prompt)
        logger.debug(f"[{self.__class__.__name__}] Raw LLM response: {raw!r}")
        cleaned = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
        try:
            data = json.loads(cleaned)
            return JobDataSanitizer().sanitize(data)
        except json.JSONDecodeError as e:
            logger.warning(
                f"[{self.__class__.__name__}] JSON parse failed, attempting repair: {e}"
            )
            repaired = _try_repair_json(cleaned)
            if repaired is not None:
                logger.info(f"[{self.__class__.__name__}] JSON repair succeeded")
                return JobDataSanitizer().sanitize(repaired)

            logger.error(
                f"[{self.__class__.__name__}] JSON repair failed, giving up on this "
                f"response. Raw (truncated): {cleaned[:300]!r}"
            )
            raise LLMParseError(f"Could not parse LLM response as JSON: {e}") from e

    def _build_expired_check_prompt(self, text: str) -> str:
        # Expiry wording is almost always near the top of a posting or in a
        # banner/interstitial, not buried at the bottom — truncate hard to
        # keep this prompt (and the model's read of it) cheap.
        snippet = text[:3000]
        return (
            "You are checking whether a scraped job-posting web page indicates "
            "that the listing is closed, expired, filled, or no longer available.\n\n"
            'Respond with ONLY a JSON object of the exact shape {"expired": true} '
            'or {"expired": false} — no other text, no markdown, no explanation.\n\n'
            'If the page clearly shows an active, open job posting, respond '
            '{"expired": false}. If it shows any indication the posting is '
            'closed, filled, expired, or no longer accepting applications, '
            'respond {"expired": true}. If the text is unclear or you are '
            'genuinely unsure, respond {"expired": false} — do not guess '
            "expired without a clear signal.\n\n"
            f"Page text:\n{snippet}"
        )

    def check_expired(self, text: str) -> Optional[bool]:
        """
        Narrow, single-purpose check: does this scraped page text indicate
        the job listing is no longer available? Unlike extract(), this needs
        no Job object — just the scraped text — and asks for a single boolean
        rather than the full multi-field extraction shape.

        Returns True/False, or None if the call failed or the response
        couldn't be parsed as a clear verdict (caller should treat None as
        inconclusive, not as "not expired").
        """
        prompt = self._build_expired_check_prompt(text)

        try:
            raw = self.complete(prompt)
        except Exception as e:
            logger.warning(
                f"[{self.__class__.__name__}] check_expired completion failed: {e}"
            )
            return None

        logger.debug(f"[{self.__class__.__name__}] Raw expired-check response: {raw!r}")
        cleaned = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            data = _try_repair_json(cleaned)

        if not isinstance(data, dict) or "expired" not in data:
            logger.warning(
                f"[{self.__class__.__name__}] check_expired: no clear verdict in "
                f"response (truncated): {cleaned[:200]!r}"
            )
            return None

        return bool(data["expired"])



# ─── Ollama (local) ────────────────────────────────────────────────────────────

class OllamaProvider(LLMProvider):
    """
    Ollama — run any model locally, no API key needed.
    Runs fully offline.

    pip install ollama
    ollama pull qwen2.5:3b-instruct  ( llama3.2, etc.)
    """

    # num_predict is a hard ceiling on generated tokens so a misbehaving
    # model (runaway repetition on messy scraped text) can't generate
    # forever; timeout is the wall-clock backstop if the server stalls.
    NUM_PREDICT = 800

    def __init__(self, model: str = "qwen2.5:3b-instruct", timeout: float = 120.0):
        self.model = model
        self.timeout = timeout
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import ollama
            except ImportError:
                raise ImportError("Run: pip install ollama")
            # ollama.Client forwards timeout straight to httpx.Client, so a
            # stuck generation raises httpx.ReadTimeout instead of hanging
            # forever. The module-level ollama.chat has no timeout at all.
            self._client = ollama.Client(timeout=self.timeout)
        return self._client

    def complete(self, prompt: str) -> str | None:
        client = self._get_client()
        response = client.chat(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            format="json",  # forces JSON output, same as response_format
            options={
                "temperature": 0,
                "num_ctx": 8192,
                "num_predict": self.NUM_PREDICT,
            },
        )
        return response["message"]["content"]