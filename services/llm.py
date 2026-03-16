from abc import ABC, abstractmethod
import json, os, re
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline
from dotenv import load_dotenv
from services.config import Config
from services.models import Job

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


def _build_prompt(job: Job, text: str) -> str:
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


# ─── Base Class ────────────────────────────────────────────────────────────────

class LLMProvider(ABC):
    """Base class for LLM providers. Implement `complete(prompt) -> str`."""

    @abstractmethod
    def complete(self, prompt: str) -> str:
        """Send prompt, return raw response text."""
        ...

    def extract(self, job: Job, text: str) -> dict:
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


# ─── Groq ──────────────────────────────────────────────────────────────────────

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

    def complete(self, prompt: str) -> str|None:
        client = self._get_client()
        response = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content




# ─── Phi-3 (local) ─────────────────────────────────────────────────────────────
class Phi3Provider(LLMProvider):
    """
    Local Microsoft Phi-3-mini via Hugging Face Transformers.
    Runs fully offline — no API key needed.
    Requires a CUDA-capable GPU for reasonable speed.

    pip install transformers torch accelerate
    """

    def __init__(self, model_id: str = "microsoft/Phi-3-mini-4k-instruct"):
        torch.random.manual_seed(0)
        model = AutoModelForCausalLM.from_pretrained(
            model_id,
            device_map="cuda",
            torch_dtype="auto",
            trust_remote_code=False,  # use transformers' built-in Phi-3 support
        )
        tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=False)
        self._pipe = pipeline("text-generation", model=model, tokenizer=tokenizer)
        self._gen_args = {
            "max_new_tokens": 500,
            "return_full_text": False,
            "temperature": 0.0,
            "do_sample": False,
        }

    def complete(self, prompt: str) -> str:
        """Wrap the shared prompt in a chat message and return the raw text response."""
        messages = [
            {"role": "system", "content": "You are a structured data extraction assistant. Output only valid JSON."},
            {"role": "user",   "content": prompt},
        ]
        output = self._pipe(messages, **self._gen_args)
        return output[0]["generated_text"].strip()