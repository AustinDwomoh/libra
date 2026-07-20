import re, json, uuid, asyncio
from typing import Optional
from Refine.llm import  LLMProvider, OllamaProvider
from Utils.constants import Config
from Utils.models import Job
from Service.Scrapper import Pirate, ScrapeResult
from Service.db import JobDatabase
from tqdm import tqdm

# ─── Stage 1: Regex ────────────────────────────────────────────────────────────
class RegexConstants:
    """Constants for regex patterns used in LLM repair and extraction"""
    def __init__(self):
        self._PAY_RE = re.compile(
            r"""
            (?P<sym>[€£\$¥₹])?
            (?P<min>[\d][,\d]*(?:\.\d+)?k?)
            \s*(?:[-–—]|to)\s*
            (?P<sym2>[€£\$¥₹])?
            (?P<max>[\d][,\d]*(?:\.\d+)?k?)
            (?:\s*(?:per\s+)?(?:hour|hr|year|yr|annual(?:ly)?|month|mo|week|wk|pa))?
            |
            (?P<sym3>[€£\$¥₹])
            (?P<single>[\d][,\d]*(?:\.\d+)?k?)
            (?:\s*(?:per\s+)?(?:hour|hr|year|yr|annual(?:ly)?|month|mo|week|wk|pa))?
            """,
            re.IGNORECASE | re.VERBOSE,
        )

        self._ROLE_RE = re.compile(
            r"\b(full[\s-]?time|part[\s-]?time|contract(?:or)?|freelance|intern(?:ship)?|temporary)\b",
            re.IGNORECASE,
        )
        self._ROLE_NORM = {
            "fulltime": "full-time", "full time": "full-time",
            "parttime": "part-time", "part time": "part-time",
            "contractor": "contract", "internship": "internship",
            "intern": "internship", "temporary": "contract", "freelance": "freelance",
        }

        self._REMOTE_RE = re.compile(
            r"\b(remote|work from home|wfh|fully remote|remote[\s-]first|anywhere)\b",
            re.IGNORECASE,
        )
        self._ONSITE_RE = re.compile(
            r"\b(on[\s-]?site|in[\s-]?office|in[\s-]?person|hybrid)\b",
            re.IGNORECASE,
        )

        self._EXP_RE = re.compile(
            r"(\d+)\s*(?:to|[-–])\s*(\d+)\s*\+?\s*years?(?:\s+of)?(?:\s+experience)?|"
            r"(\d+)\+\s*years?(?:\s+of)?(?:\s+experience)?|"
            r"(\d+)\s*years?\s+(?:of\s+)?experience",
            re.IGNORECASE,
        )

        # Words that, within a few chars of a number match, indicate it's actually
        # talking about pay rather than e.g. years of experience, headcount, etc.
        self._PAY_KEYWORD_RE = re.compile(
            r"\b(salary|compensation|pay|wage|hourly|annual(?:ly)?|stipend|earn|earning|per\s+(?:hour|year|month|week|annum))\b",
            re.IGNORECASE,
        )

        # Words that, if found right next to a number range, signal it's NOT pay
        # (years of experience, headcount, ratings, etc.) — vetoes even when a
        # currency symbol/k-suffix is present in edge cases like "$10-15 years exp".
        self._NON_PAY_KEYWORD_RE = re.compile(
            r"\b(years?|yrs?|months?|weeks?|days?|hours?\s+(?:per|a)\s+week|people|employees|reports|stars?|reviews?)\b",
            re.IGNORECASE,
        )

        self._PAY_CONTEXT_WINDOW = 25  # chars to look before/after a bare number match for anchor keywords

    def _has_pay_anchor(self,match: "re.Match", text: str) -> bool:
        """
        A bare numeric range (no currency symbol, no 'k' suffix, no per-hour/year
        suffix captured in the regex itself) needs extra context before we trust
        it's actually a salary and not e.g. '10-15 years experience'.
        """
        start = max(0, match.start() - self._PAY_CONTEXT_WINDOW)
        end = min(len(text), match.end() + self._PAY_CONTEXT_WINDOW)
        window = text[start:end]

        if self._NON_PAY_KEYWORD_RE.search(window):
            return False
        if self._PAY_KEYWORD_RE.search(window):
            return True
        return False

    def _time_unit_is_real_word(self, m: "re.Match", text: str) -> bool:
        """
        _PAY_RE's optional suffix group has no trailing \\b, so against text like
        "10-15 years experience" it can match just "year" out of "years" — and a
        boundary check against the truncated match group alone would wrongly see
        end-of-string as a word boundary. Check the real next character in the
        full source text instead: if it's a word char (the "s" in "years"), the
        "time unit" was actually just a prefix of a longer word, not a real anchor.
        """
        if m.end() >= len(text):
            return True
        return not text[m.end()].isalnum()

    def regex_pay(self, text: str) -> Optional[list]:
        """Returns [min, max] or None."""
        for m in self._PAY_RE.finditer(text):
            g = m.groupdict()

            # Does this match carry its own anchor (currency symbol, 'k' suffix,
            # or a captured time-unit like 'hour'/'year')? If not, it's a bare
            # number range and needs a nearby pay keyword to be trusted.
            has_symbol = bool(g.get("sym") or g.get("sym2") or g.get("sym3"))
            has_k_suffix = any(
                (g.get(key) or "").lower().endswith("k")
                for key in ("min", "max", "single")
            )
            matched_time_unit = re.search(
                r"(?:per\s+)?(?:hour|hr|year|yr|annual(?:ly)?|month|mo|week|wk|pa)\s*$",
                m.group(0), re.IGNORECASE,
            )
            has_time_unit = bool(matched_time_unit) and self._time_unit_is_real_word(m, text)

            if not (has_symbol or has_k_suffix or has_time_unit):
                if not self._has_pay_anchor(m, text):
                    continue

            try:
                if g.get("min") and g.get("max"):
                    min_raw, max_raw = g["min"], g["max"]
                    # Shorthand like "90-110k": k-suffix often only appears on the
                    # second number but applies to both. Propagate it to min.
                    if max_raw.lower().endswith("k") and not min_raw.lower().endswith("k"):
                        min_raw = f"{min_raw}k"
                    lo, hi = Config._norm_amount(min_raw), Config._norm_amount(max_raw)
                    if lo < 10 or hi < 10:
                        continue
                    return [lo, hi]
                elif g.get("single"):
                    amt = Config._norm_amount(g["single"])
                    if amt < 10:
                        continue
                    return [amt, None]
            except (ValueError, TypeError):
                continue
        return None

    def regex_remote(self, text: str) -> Optional[bool]:
        if self._REMOTE_RE.search(text):
            return True
        if self._ONSITE_RE.search(text):
            return False
        return None


    def regex_role_type(self, text: str) -> Optional[str]:
        m = self._ROLE_RE.search(text)
        if m:
            raw = re.sub(r"[-\s]", "", m.group(0).lower())
            return self._ROLE_NORM.get(raw, m.group(0).lower())
        return None


    def regex_experience(self, text: str) -> Optional[str]:
        m = self._EXP_RE.search(text)
        if not m:
            return None
        g = m.groups()
        if g[0] and g[1]:
            return f"{g[0]}-{g[1]}"
        elif g[2]:
            return f"{g[2]}+"
        elif g[3]:
            return g[3]
        return None

    def run_regex_stage(self, job: "Job") -> dict:
        """Run regex over job description. Returns dict of extracted fields."""
        desc = Config.strip_html(job.description or "")
        full_text = f"{job.title or ''} {desc}"
        extracted = {}

        if Config.is_missing(job.pay_range):
            pay = self.regex_pay(full_text)
            if pay:
                extracted["pay_range"] = pay

        if Config.is_missing(job.is_remote):
            remote = self.regex_remote(full_text)
            if remote is not None:
                extracted["is_remote"] = remote

        if Config.is_missing(job.role_type):
            role = self.regex_role_type(full_text)
            if role:
                extracted["role_type"] = role

        if Config.is_missing(job.tags):
            exp = self.regex_experience(full_text)
            if exp:
                extracted["tags"] = {"experience_years": exp}

        return extracted


class JobEnricher:
    """
    A class to encapsulate the job enrichment process.
    This allows for stateful configuration and easier testing.
    """

    def __init__(self,job_id: uuid.UUID, provider: Optional[LLMProvider] = None, use_llm: bool = True, llm_delay: float = 0.5):
        self.job_id = job_id
        self.provider = provider or OllamaProvider()
        self.use_llm = use_llm
        self.llm_delay = llm_delay
        self.fields_to_check = ["pay_range", "is_remote", "role_type", "location", "tags", "description"]
        self.meta = {
                "stages_run": [],
                "fields_filled": [],
                "provider": provider.__class__.__name__ if provider else None,
            }
        self.regex_constants = RegexConstants()
        self.scrapper = Pirate()
        
    def _apply_to_job(self, job: "Job", extracted: dict) -> list[str]:
        """
        Write extracted fields onto the Job instance.
        Only fills fields that are currently missing.
        Returns list of field names that were updated.
        """
        filled = []

        for field_name, value in extracted.items():
            # job_expired is a control signal handled by the caller (_mark_expired),
            # never a Job attribute — skip it here regardless of whether the caller
            # already popped it, so this function stays safe on its own.
            if field_name == "job_expired":
                continue

            if value is None:
                continue

            if field_name == "tags":
                if not isinstance(value, dict):
                    continue

                current = job.tags
                # tags can come back from the DB as a raw JSON string ("{}", "null")
                # instead of a parsed dict — normalize before treating it as "existing".
                if isinstance(current, str):
                    try:
                        current = json.loads(current) if current.strip() else {}
                    except json.JSONDecodeError:
                        current = {}

                existing = current if isinstance(current, dict) else {}
                merged = {**value, **existing}  # existing keys take priority
                if merged != existing:  # only count it as "filled" if something new landed
                    job.tags = merged
                    filled.append("tags")
                else:
                    job.tags = merged  # still normalize the type even if nothing changed
                continue

            current = getattr(job, field_name, None)
            if not Config.is_missing(current):
                continue  # never overwrite existing data

            setattr(job, field_name, value)
            filled.append(field_name)

        return filled
    
    async def _handle_scraped_text(self, job: "Job", scraped: str|None|dict|ScrapeResult) -> Optional[dict]:
        if scraped is None or (isinstance(scraped, dict)):
            return

        status = self.scrapper.classify_scraped_text(scraped.raw_text)  #type: ignore
        if status == "expired":
            self.meta["stages_run"].append("scrape_expired")
            await self._mark_expired()
            return
        if status == "garbage":
            self.meta["stages_run"].append("scrape_garbage")
            return

        self.meta["stages_run"].append("regex_scraped")

        # snapshot BEFORE filling description, so the LLM gate reflects what was
        # actually missing when we started, not what's left after our own fill
        was_missing_before_fill = self._missing_fields(job)

        if Config.is_missing(job.pay_range):
            pay = self.regex_constants.regex_pay(scraped.raw_text) #type: ignore
            if pay:
                job.pay_range = pay
                self.meta["fields_filled"].append("pay_range (regex+scrape)")

        if Config.is_missing(job.is_remote):
            remote = self.regex_constants.regex_remote(scraped.raw_text) #type: ignore
            if remote is not None:
                job.is_remote = remote
                self.meta["fields_filled"].append("is_remote (regex+scrape)")

        if Config.is_missing(job.role_type):
            role = self.regex_constants.regex_role_type(scraped.raw_text) #type: ignore
            if role:
                job.role_type = role
                self.meta["fields_filled"].append("role_type (regex+scrape)")

        if Config.is_missing(job.description):
            job.description = scraped.trimmed_text[:50000]#type:ignore
            self.meta["fields_filled"].append("description (scraped-trimmed)")

        # use the snapshot, not a fresh _missing_fields(job) call
        if "description" in was_missing_before_fill and self.use_llm and self.provider:
            self.meta["stages_run"].append("llm_scraped")
            extracted = self.provider.extract(job, scraped.trimmed_text) #type: ignore

            job_expired = extracted.pop("job_expired", None)
            if job_expired:
                self.meta["stages_run"].append("llm_expired")
                return await self._mark_expired()

            desc_valid = extracted.pop("description_looks_valid", None)
            if desc_valid is False:
                self.meta["stages_run"].append("description_flagged_invalid")
                self.meta.setdefault("warnings", []).append(
                    f"job {self.job_id}: scraped description flagged as invalid by LLM"
                )

            llm_summary = extracted.pop("summary", None)
            if llm_summary and Config.is_missing(job.summary):
                job.summary = llm_summary
                self.meta["fields_filled"].append("summary (llm+scrape)")

            filled = self._apply_to_job(job, extracted)
            self.meta["fields_filled"].extend(f"{f} (llm+scrape)" for f in filled)

        Config.logger.info(f"Finished enriching job: {job.title} at {job.company} for {job}")
        Config.logger.info(f"Done. Filled: {self.meta['fields_filled']}")
        return self.meta
    
    def _apply_structured_data(self, job: "Job", structured: dict) -> list[str]:
        """
        Apply schema.org JobPosting fields authoritatively. Unlike _apply_to_job,
        this OVERWRITES existing values — structured markup comes straight from
        the employer, so it's treated as the true source even if the job already
        had a (possibly stale/wrong) value for the same field from its original
        listing source.
        """
        filled = []
        for field_name in ("location", "is_remote", "pay_range", "description"):
            if field_name in structured and structured[field_name] is not None:
                setattr(job, field_name, structured[field_name])
                filled.append(field_name)
        return filled
        
    def _missing_fields(self, job: "Job") -> list[str]:
        """Return a list of fields that are missing from the job."""
        return [f for f in self.fields_to_check if Config.is_missing(getattr(job, f, None))]
    
    async def _run_regex(self, job: "Job") -> None:
        desc = Config.strip_html(job.description or "")

        if len(desc.strip()) <= 100:
            return

        self.meta["stages_run"].append("regex")
        extracted = self.regex_constants.run_regex_stage(job)
        filled = self._apply_to_job(job, extracted)
        self.meta["fields_filled"].extend( f"{field} (regex)" for field in filled)

    async def _mark_expired(self):
        """Shared exit path for any stage that determines the listing is expired."""
        db = await JobDatabase.create()
        await db.update( table="job_list", filters={"id": self.job_id}, data={"status": "expired", "enriched": True},)
        self.meta["expired"] = True
        Config.logger.info(f"Done. Filled: {self.meta['fields_filled']}")
        
    async def _run_scrape(self, job: "Job"):
        if not job.apply_url:
            return
        missing = self._missing_fields(job)
        Config.logger.info(f"Scraping apply URL for: {missing}")
   
        self.meta["stages_run"].append("scrape")
        scraped = await self.scrapper.scrape_apply_url(job.apply_url)

        if isinstance(scraped, dict):
            self.meta["stages_run"].append("structured_data")
            if scraped.get("job_expired"):
                self.meta["stages_run"].append("structured_expired")
                await self._mark_expired()
                return
            filled = self._apply_structured_data(job, scraped)

            self.meta["fields_filled"].extend(f"{f} (structured)"for f in filled)

            if (self._missing_fields(job) and self.use_llm and self.provider ):
                Config.logger.info(f"LLM on structured description for: {missing}")
                self.meta["stages_run"].append("llm_structured_desc")
                extracted = self.provider.extract(job, scraped.get("description"))#type: ignore
                #since if its sturtured u can just uses the get dict

                job_expired = extracted.pop("job_expired", None)
                if job_expired:
                    self.meta["stages_run"].append("llm_expired")
                    return await self._mark_expired()

                desc_valid = extracted.pop("description_looks_valid", None)
                if desc_valid is False:
                    self.meta["stages_run"].append("description_flagged_invalid")
                    self.meta.setdefault("warnings", []).append(
                        f"job {self.job_id}: scraped description flagged as invalid by LLM"
                    )

                llm_summary = extracted.pop("summary", None)
                if llm_summary and Config.is_missing(job.summary):
                    job.summary = llm_summary
                    self.meta["fields_filled"].append("summary (llm)")

                filled = self._apply_to_job(job, extracted)
                self.meta["fields_filled"].extend(f"{f} (llm+structured)" for f in filled)
                Config.logger.info(f"Finished enriching job: {job.title} at {job.company} for {job}")
                Config.logger.info(f"Done. Filled: {self.meta['fields_filled']}")
                return self.meta
           
        Config.logger.info(f"Scraped text length: raw={len(scraped.raw_text)}, trimmed={len(scraped.trimmed_text)}")  #type: ignore
        Config.logger.debug(f"Scraped text (trimmed): {scraped.trimmed_text[:500]}")     #type: ignore

        await self._handle_scraped_text(job, scraped)

    async def enrich_job(self, job: "Job") -> dict:
        Config.logger.info(f"Enriching job: {job.title} at {job.company} for {job}")
        if not self._missing_fields(job):
            Config.logger.info("Job already complete, skipping enrichment")
            return self.meta
        Config.logger.info(f"Enriching '{job.title}' — missing: {self._missing_fields(job)}")
        
        await self._run_regex(job) #stage 1: regex
       
        #stage 2: scrape apply_url if missing fields and apply_url exists
        if self._missing_fields(job):
            await self._run_scrape(job)
        
        return self.meta
        
        
    

    async def enrich_jobs_batch(self, jobs: list["Job"],provider: Optional[LLMProvider] = None,use_llm: bool = True,llm_delay: float = 0.5,) -> list[dict]:
        """
        Enrich a list of Job instances in-place.
        Returns list of meta dicts (one per job).
        llm_delay: seconds between LLM calls to respect free tier rate limits.
        """
        if use_llm and provider is None:
            provider = OllamaProvider()

        results = []
        with tqdm(total=len(jobs), desc="Enriching Batch Jobs", unit="job", ncols=100) as pbar:
            for i, job in enumerate(jobs):
                Config.logger.info(f"Job {i+1}/{len(jobs)}")
                meta = await self.enrich_job(job)
                results.append(meta)
                if self.use_llm and i < len(jobs) - 1:
                    await asyncio.sleep(self.llm_delay)
                pbar.update(1)
        return results

# ─── Example ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    
    company_id = uuid.UUID("6c8333ed-7275-4565-9392-81a9aa46aa45")
    job_id = uuid.uuid4()
    job1 = Job(
        title="Associate Web Developer (.Net)",
        company=company_id,
        location="",
        is_remote=False,
        description="",
        apply_url="https://tencent.wd1.myworkdayjobs.com/Tencent_Careers/job/US-California-Palo-Alto/Hunyuan-Multimodal-Algorithm-Researcher-Intern-Omni-Modal---_R107051?ref=Simplify",
        role_type="other",
        pay_range=None,
        source="simplify",
        tags={},
    )

    print("=== Before ===")
    print(job1)


    # Swap provider here —  or GeminiProvider()
    extractor = JobEnricher(job_id=job_id, provider=OllamaProvider(), use_llm=True, llm_delay=0.5)
    meta = asyncio.run(extractor.enrich_job(job1))

    print("\n=== After ===")
    print(job1)
    print(f"\nmeta: {json.dumps(meta, indent=2)}") 
    #print(asyncio.run(scrape_apply_url("https://generac.wd5.myworkdayjobs.com/en-US/external/job/Waukesha-WI---USA/Intern-IT---Application-Development--Data-Integration_JR12491?utm_source=Simplify&ref=Simplify")))
    #print(asyncio.run(scrape_apply_url("https://tencent.wd1.myworkdayjobs.com/Tencent_Careers/job/US-California-Palo-Alto/Hunyuan-Multimodal-Algorithm-Researcher-Intern-Omni-Modal---_R107051?ref=Simplify")))