from abc import ABC, abstractmethod
import json,os,re
from dotenv import load_dotenv
from services.config import Config
from services.companies import Job
load_dotenv()

_LLM_PROMPT = """Extract structured data from this job posting.
Return ONLY valid JSON, no markdown, no explanation.

Schema:
{{
  "title": string or null,
  "location": string or null,
  "is_remote": true | false | null,
  "role_type": "full-time" | "part-time" | "contract" | "internship" | "freelance" | "other" | null,
  "pay_range": [min_number, max_number] or [min_number, null] or null,
  "description": string or null,
  "tags": {{
    "experience_years": string or null,
    "skill_0": string,
    "skill_1": string
    ... up to 10 hard skills as skill_0, skill_1, etc.
  }} or null
}}

Rules:
- pay_range must be a 2-element array: [min, max]. Use null for max if only one value.
  Convert shorthand: 80k -> 80000. Return null if no salary info at all.
- is_remote: true if fully remote, false if on-site or hybrid, null if unclear
- role_type: default "other" if not determinable
- tags: experience_years as "5+" or "3-5", plus top hard/technical skills only
- location: city/country only, null if not mentioned
- description: clean plain-text summary of the role (2-4 sentences). null if not enough info.

Already known (do not override):
{known}

Job posting:
{text}
"""



def _build_prompt(job: "Job", text: str) -> str:
    known = {
        "title":     job.title     if not Config.is_missing(job.title)     else None,
        "location":  job.location  if not Config.is_missing(job.location)  else None,
        "is_remote": job.is_remote if not Config.is_missing(job.is_remote) else None,
        "role_type": job.role_type if not Config.is_missing(job.role_type) else None,
        "pay_range": job.pay_range if not Config.is_missing(job.pay_range) else None,
    }
    return _LLM_PROMPT.format(
        known=json.dumps({k: v for k, v in known.items() if v is not None}, indent=2),
        text=text[:4000],
    )

def _normalise_pay(data: dict) -> dict:
    """Ensure pay_range is always [min, max] format."""
    if "pay_range" in data and data["pay_range"] is not None:
        pr = data["pay_range"]
        if isinstance(pr, list) and len(pr) >= 2:
            data["pay_range"] = [pr[0], pr[1]]
        elif isinstance(pr, list) and len(pr) == 1:
            data["pay_range"] = [pr[0], None]
        else:
            data["pay_range"] = None
    return data




class LLMProvider(ABC):
    """Base class for LLM providers. Implement `complete(prompt) -> str`."""

    @abstractmethod
    def complete(self, prompt: str) -> str:
        """Send prompt, return raw response text."""
        ...

    def extract(self, job, text: str) -> dict:
        """Build prompt, call LLM, parse and return extracted fields."""
        prompt = _build_prompt(job, text)
        try:
            raw = self.complete(prompt)
            raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
            data = json.loads(raw)
            return _normalise_pay(data)
        except Exception as e:
            Config.logger.error(f"[{self.__class__.__name__}] LLM failed: {e}")
            return {}


# ─── Groq Provider ─────────────────────────────────────────────────────────────

class GroqProvider(LLMProvider):
    """
    Groq — recommended default.
    Free tier: 14,400 req/day, no credit card needed.
    Get key: https://console.groq.com

    pip install groq
    GROQ_API_KEY=your_key
    """

    def __init__(self, model: str = "llama-3.3-70b-versatile"):
        self.model = model
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from groq import Groq
            except ImportError:
                raise ImportError("Run: pip install groq")
            api_key = os.getenv("GROQ_API_KEY")
            if not api_key:
                raise ValueError("Set GROQ_API_KEY environment variable")
            self._client = Groq(api_key=api_key)
        return self._client

    def complete(self, prompt: str) -> str:
        client = self._get_client()
        response = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"},  # guarantees valid JSON
        )
        return response.choices[0].message.content


# ─── Gemini Provider ───────────────────────────────────────────────────────────

class GeminiProvider(LLMProvider):
    """
    Google Gemini via google-genai SDK.
    Free tier: 1,500 req/day.
    Get key: https://aistudio.google.com/app/apikey

    pip install google-genai
    GEMINI_KEY=your_key
    """

    def __init__(self, model: str = "gemini-2.5-flash-preview-04-17"):
        self.model = model
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from google import genai
            except ImportError:
                raise ImportError("Run: pip install google-genai")
            api_key = os.getenv("GEMINI_KEY")
            if not api_key:
                raise ValueError("Set GEMINI_KEY environment variable")
            self._client = genai.Client(api_key=api_key)
        return self._client

    def complete(self, prompt: str) -> str:
        client = self._get_client()
        response = client.models.generate_content(
            model=self.model,
            contents=prompt,
        )
        return response.text.strip()

