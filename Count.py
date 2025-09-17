import requests, json, csv
import pandas as pd
from bs4 import BeautifulSoup
from rapidfuzz import fuzz

class Azalea_:
    def __init__(self, url=None):
        self.url = url or "https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/README.md"
        self.readme_text = None
        self.jobs = []

    def fetch_readme(self):
        resp = requests.get(self.url)
        if resp.status_code != 200:
            raise Exception(f"Failed to fetch README, status {resp.status_code}")
        self.readme_text = resp.text
        return self.readme_text

    def parse_tables(self):
        if not self.readme_text:
            raise Exception("README not fetched yet. Call fetch_readme() first.")
        soup = BeautifulSoup(self.readme_text, "html.parser")
        jobs = []

        for table in soup.find_all("table"):
            current_company = None
            for tr in table.find_all("tr"):
                tds = tr.find_all("td")
                if not tds:
                    continue
                first_col_text = tds[0].get_text(strip=True)
                if first_col_text != "↳":
                    current_company = first_col_text
                company = current_company

                title = tds[1].get_text(strip=True) if len(tds) > 1 else ""
                location = tds[2].get_text(strip=True) if len(tds) > 2 else ""
                app_link = None
                if len(tds) > 3:
                    a_tag = tds[3].find("a", href=True)
                    if a_tag:
                        app_link = a_tag['href']

                jobs.append({
                    "company": company,
                    "title": title,
                    "location": location,
                    "link": app_link
                })

        self.jobs = jobs
        print(f"✅ Parsed {len(jobs)} job entries")
        return jobs

    def tag_sponsorship(self, sponsorship_db, use_fuzzy=False, threshold=90):
        if not self.jobs:
            self.parse_tables()

        for job in self.jobs:
            company = job["company"]
            if use_fuzzy:
                job["sponsorship"] = (
                    "✅ Likely sponsorship" if sponsorship_db.fuzzy_match(company, threshold)
                    else "❌ No record found"
                )
            else:
                job["sponsorship"] = (
                    "✅ Likely sponsorship" if sponsorship_db.has_sponsorship(company)
                    else "❌ No record found"
                )

        with open("tagged_jobs.json", "w", encoding="utf-8") as f:
            json.dump(self.jobs, f, indent=2)
        print("🏷️ Sponsorship tagging complete")

    def run(self, use_fuzzy=False):
        self.fetch_readme()
        self.parse_tables()
        sponsorship_db = SponsorshipDB(csv_paths=["Employer_info.csv"])
        if sponsorship_db:
            self.tag_sponsorship(sponsorship_db, use_fuzzy=use_fuzzy)
        return self.jobs


class SponsorshipDB:
    def __init__(self, csv_paths=None):
        self.employers = set()
        if csv_paths:
            for path in csv_paths:
                self._load_csv(path)

    def _load_csv(self, path):
        df = pd.read_csv(path, low_memory=False)
        possible_cols = [
    'EmployerName',
    'Employer',
    'Employer_Name',
    'CompanyName',
    'Employer (Petitioner) Name'  # <-- Add this
]

        for col in possible_cols:
            if col in df.columns:
                names = df[col].dropna().astype(str)
                for name in names:
                    self.employers.add(self._normalize(name))
                break

    def _normalize(self, s):
        return s.strip().lower()

    def has_sponsorship(self, company_name):
        return self._normalize(company_name) in self.employers

    def fuzzy_match(self, company_name, threshold=90):
        target = self._normalize(company_name)
        for employer in self.employers:
            if fuzz.ratio(employer, target) >= threshold:
                return True
        return False