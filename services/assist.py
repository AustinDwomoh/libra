from rapidfuzz import fuzz
import pandas as pd

class SponsorshipDB:
    def __init__(self, csv_paths=None):
        self.employers = set()
        if csv_paths:
            for path in csv_paths:
                self._load_csv(path)

    def _load_csv(self, path):
        for encoding in ['utf-16', 'utf-8', 'latin-1', 'cp1252']:
            for sep in ['\t', ',', ';']:
                try:
                    df = pd.read_csv(path, low_memory=False, encoding=encoding, sep=sep, on_bad_lines='skip')
                    if len(df.columns) > 1:
                        break
                except Exception:
                    continue
            if len(df.columns) > 1:
                break
        else:
            raise ValueError(f"Could not read CSV file with any supported encoding: {path}")

        employer_columns = [
            'EmployerName',
            'Employer',
            'Employer_Name',
            'CompanyName',
            'Employer (Petitioner) Name'
        ]

        for column in employer_columns:
            if column in df.columns:
                employer_names = df[column].dropna().astype(str)
                self.employers.update(self._normalize(name) for name in employer_names)
                break

    def _normalize(self, company):
        return company.strip().lower()

    def has_sponsorship(self, company_name):
        return self._normalize(company_name) in self.employers

    def fuzzy_match(self, company_name, threshold=90):
        if company_name:
            normalized_target = self._normalize(company_name)
            return any(fuzz.ratio(employer, normalized_target) >= threshold for employer in self.employers)
        return False