from abc import ABC, abstractmethod
import json,re
#for when we later want to add a local model option:
#import os,torch
#from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline

from Utils.constants import Config
from Utils.models import Job
from Utils.sanitate import JobDataSanitizer 

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
    (e.g. Ollama qwen2.5 variants) sometimes emit trailing commas, smart
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

    # 2) Normalise smart/curly quotes to straight quotes.
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
        Config.logger.debug(f"[{self.__class__.__name__}] Raw LLM response: {raw!r}")
        cleaned = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
        try:
            data = json.loads(cleaned)
            return JobDataSanitizer().sanitize(data)
        except json.JSONDecodeError as e:
            Config.logger.warning(
                f"[{self.__class__.__name__}] JSON parse failed, attempting repair: {e}"
            )
            repaired = _try_repair_json(cleaned)
            if repaired is not None:
                Config.logger.info(f"[{self.__class__.__name__}] JSON repair succeeded")
                return JobDataSanitizer().sanitize(repaired)

            Config.logger.error(
                f"[{self.__class__.__name__}] JSON repair failed, giving up on this "
                f"response. Raw (truncated): {cleaned[:300]!r}"
            )
            raise LLMParseError(f"Could not parse LLM response as JSON: {e}") from e


# ─── Groq ──────────────────────────────────────────────────────────────────────
#Trying to fully relly on Ollama for now, since Groq is a paid service and Ollama is free and local.
#class GroqProvider(LLMProvider):
#    """
#    Groq — recommended default.
#    Free tier: 14,400 req/day, no credit card needed.
#    Get key: https://console.groq.com
#
#    pip install groq
#    GROQ_API_KEY=your_key
#    """
#
#    def __init__(self, model: str = "qwen/qwen3.6-27b"):
#        self.model = model
#        self._client = None
#
#    def _get_client(self):
#        if self._client is None:
#            try:
#                from groq import Groq
#            except ImportError:
#                raise ImportError("Run: pip install groq")
#            api_key = Config.GROQ_API_KEY
#            if not api_key:
#                raise ValueError("Set GROQ_API_KEY environment variable")
#            self._client = Groq(api_key=api_key)
#        return self._client
#
#    def complete(self, prompt: str) -> str|None:
#        client = self._get_client()
#        response = client.chat.completions.create(
#            model=self.model,
#            messages=[{"role": "user", "content": prompt}],
#            temperature=0,
#            response_format={"type": "json_object"},
#        )
#        return response.choices[0].message.content

#never gonna use the Phi3

# ─── Ollama (local) ────────────────────────────────────────────────────────────

class OllamaProvider(LLMProvider):
    """
    Ollama — run any model locally, no API key needed.
    Runs fully offline.

    pip install ollama
    ollama pull deepseek-r1:8b  (or qwen2.5:7b, llama3.2, etc.)
    """

    def __init__(self, model: str = "deepseek-r1:8b"):
        self.model = model
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import ollama
            except ImportError:
                raise ImportError("Run: pip install ollama")
            self._client = ollama
        return self._client

    def complete(self, prompt: str) -> str | None:
        client = self._get_client()
        response = client.chat(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            format="json",  # forces JSON output, same as response_format
            options={"temperature": 0, "num_ctx": 8192},
        )
        return response["message"]["content"]