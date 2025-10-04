from rapidfuzz import fuzz, process
import pandas as pd
import json
from pathlib import Path
from typing import Set, List, Optional


class SponsorshipDB:
    """Database of employers likely to sponsor visas, built from CSV(s)."""

    ENCODINGS = ["utf-16", "utf-8", "latin-1", "cp1252"]
    SEPARATORS = ["\t", ",", ";"]
    EMPLOYER_COLUMNS = [
        "EmployerName",
        "Employer",
        "Employer_Name",
        "CompanyName",
        "Employer (Petitioner) Name",
    ]

    def __init__(self, csv_paths: Optional[List[str]] = None, cache_file: str = "cache/sponsors.json"):
        self.employers: Set[str] = set()
        self.cache_file = Path(cache_file)
        self.csv_paths = csv_paths or []

        # Ensure cache directory exists
        self.cache_file.parent.mkdir(exist_ok=True, parents=True)

        if self.csv_paths:
            self._load_with_cache_check()

    # ---------------- Cache Handling ----------------

    def _csv_has_changed(self) -> bool:
        """Check if any CSV file has been modified since last cache build."""
        if not self.cache_file.exists():
            return True

        cache_mtime = self.cache_file.stat().st_mtime
        for csv_path in self.csv_paths:
            csv_file = Path(csv_path)
            if not csv_file.exists():
                continue
            if csv_file.stat().st_mtime > cache_mtime:
                return True
        return False

    def _load_with_cache_check(self):
        """Load from cache or rebuild if CSV changed."""
        if self._csv_has_changed():
            print("CSV changed or cache missing - rebuilding...")
            self._rebuild_cache()
        else:
            print("Loading from cache...")
            self._load_from_cache()

    def _load_from_cache(self):
        """Load company names from JSON cache."""
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.employers = set(data.get("employers", []))
            print(f"✓ Loaded {len(self.employers)} employers from cache")
        except Exception as e:
            print(f"Cache load failed: {e}. Rebuilding...")
            self._rebuild_cache()

    def _rebuild_cache(self):
        """Parse CSVs and save to cache."""
        self.employers.clear()

        for csv_path in self.csv_paths:
            print(f"Parsing: {csv_path}")
            self.employers.update(self._parse_csv(csv_path))

        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(
                    {"employers": sorted(self.employers), "csv_files": self.csv_paths},
                    f,
                    indent=2,
                )
            print(f"✓ Cached {len(self.employers)} employers to {self.cache_file}")
        except Exception as e:
            print(f"Warning: Could not save cache: {e}")

    def force_rebuild(self):
        """Manually force cache rebuild."""
        print("Forcing cache rebuild...")
        self._rebuild_cache()

    # ---------------- CSV Parsing ----------------

    def _parse_csv(self, path: str, min_cases: int = 3) -> Set[str]:
        """Parse a CSV, filter for valid sponsorships, and extract employers with enough cases."""
        df = self._load_csv(path)
        if df is None:
            raise ValueError(f"Could not read CSV: {path}")

        # Keep only sponsorship rows
        df = self._filter_sponsorships(df)

        # Find employer column
        for column in self.EMPLOYER_COLUMNS:
            if column in df.columns:
                # Normalize employer names
                employer_names = df[column].dropna().astype(str).map(self._normalize)

                # Count frequency
                counts = employer_names.value_counts()

                # Only keep frequent sponsors
                filtered = counts[counts >= min_cases].index
                employers = set(filtered)

                print(f"  Found {len(employers)} strong-sponsor employers (≥{min_cases} cases)")
                return employers

        return set()

    def _load_csv(self, path: str) -> Optional[pd.DataFrame]:
        """Try multiple encodings/separators until CSV loads."""
        for encoding in self.ENCODINGS:
            for sep in self.SEPARATORS:
                try:
                    df = pd.read_csv(
                        path,
                        encoding=encoding,
                        sep=sep,
                        low_memory=False,
                        on_bad_lines="skip",
                    )
                    if len(df.columns) > 1:
                        return df
                except Exception:
                    continue
        return None

    def _filter_sponsorships(self, df: pd.DataFrame) -> pd.DataFrame:
        """Filter rows to those that likely represent valid visa sponsorships."""
        if "VisaClass" in df.columns:
            df = df[df["VisaClass"].astype(str).str.contains("H-1B", case=False, na=False)]
        if "CaseStatus" in df.columns:
            df = df[df["CaseStatus"].astype(str).str.contains("Approved|Certified", case=False, na=False)]
        return df

    # ---------------- Matching ----------------

    def _normalize(self, company: str) -> str:
        """Normalize company name for matching."""
        return (
            company.strip()
            .lower()
            .replace(",", "")
            .replace(".", "")
            .replace("inc", "")
            .replace("llc", "")
            .replace("corp", "")
        )

    def has_sponsorship(self, company_name: str) -> bool:
        """Exact match check."""
        return self._normalize(company_name) in self.employers

    def fuzzy_match(self, company_name: str, threshold: int = 90) -> bool:
        """Fuzzy match against employer list."""
        if not company_name or not self.employers:
            return False

        normalized = self._normalize(company_name)

        # Exact match first
        if normalized in self.employers:
            return True

        # Fuzzy match (RapidFuzz can do best-match search instead of loop)
        match, score, _ = process.extractOne(
            normalized, self.employers, scorer=fuzz.ratio
        )
        return score >= threshold
