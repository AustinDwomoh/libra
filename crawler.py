import requests,json,csv
import pandas as pd
from bs4 import BeautifulSoup
class Zodiac:
    def __init__(self, url=None):
        self.url = url or "https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/README.md"
        self.readme_text = None
        self.tables = []

    def fetch_readme(self):
        """Download README.md from GitHub."""
        resp = requests.get(self.url)
        if resp.status_code != 200:
            raise Exception(f"Failed to fetch README, status {resp.status_code}")
        self.readme_text = resp.text
        return self.readme_text

    def parse_tables(self):
        """Parse all tables from README and propagate parent company to child jobs."""
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

        with open('jobs.json', 'w', encoding='utf-8') as f:
            json.dump(jobs, f, indent=2)
        print(f"✅ Tables parsed and company names propagated")
        return self.tables

    def make_json(self, csv_file, json_file):
         # Load CSV into DataFrame
        df = pd.read_csv(csv_file,encoding='utf-16')

        # Replace NaNs with empty strings for cleaner JSON
        df.fillna("", inplace=True)

        # Convert to list of dictionaries
        records = df.to_dict(orient="records")

        # Save to JSON file
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2)

        print(f"✅ Converted {len(records)} records to {json_file}")

class SponsorshipChecker:
    def __init__(self, h1b_file="h1b_data.csv", no_sponsor_file="no_sponsor.txt"):
        self.h1b_companies = set(pd.read_csv(h1b_file)["Company"].str.lower())
        with open(no_sponsor_file, "r") as f:
            self.no_sponsor = set(line.strip().lower() for line in f)

    def check(self, company):
        c = company.lower()
        if c in self.no_sponsor:
            return "❌ No sponsorship"
        elif c in self.h1b_companies:
            return "✅ Likely sponsorship"
        else:
            return "❓ Unknown"


class SponsorshipDB:
    def __init__(self, csv_paths=None):
        """
        csv_paths: list of paths to CSV files that include employer names that have done H-1B / LCA filings
        """
        self.employers = set()
        if csv_paths:
            for path in csv_paths:
                self._load_csv(path)

    def _load_csv(self, path):
        df = pd.read_csv(path, low_memory=False)
        # The column names differ depending on source; try common ones
        possible_cols = ['EmployerName', 'Employer', 'Employer_Name', 'CompanyName']
        for col in possible_cols:
            if col in df.columns:
                names = df[col].dropna().astype(str)
                for name in names:
                    self.employers.add(self._normalize(name))
                break

    def _normalize(self, s):
        return s.strip().lower()

    def has_sponsorship(self, company_name):
        normalized = self._normalize(company_name)
        return normalized in self.employers
    

Zodiac().make_json(csv_file='Employer Information.csv',json_file='H1b.json')



