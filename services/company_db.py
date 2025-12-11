"""
company_db.py - Evidence-based visa sponsorship database.

Tracks:
    total H1B filings
    certified approvals
    approval rate
    reliability score (0–100)
    sponsors_visas boolean (derived from certified evidence)
"""

import psycopg2
from psycopg2.extras import execute_values
from typing import Optional, List, Dict, Set
from pathlib import Path
import pandas as pd
from rapidfuzz import fuzz, process

from services.config import Config
from services.constants import (
    CompanyValidation,
    CSVConfig,
    VisaConfig,
    FuzzyMatchConfig,
)

logger = Config.logger


# ======================================================================
# COMPANY DATABASE
# ======================================================================

class CompanyDatabase:
    """
    Database manager for H1B sponsorship data.
    Uses real certified case counts to determine sponsorship reliability.
    """

    def __init__(self, connection=None):
        if connection:
            self.conn = connection
            self.cursor = self.conn.cursor()
            self.owns_connection = False
        else:
            from services.db_manager import get_db_connection
            self.conn = get_db_connection()
            self.cursor = self.conn.cursor()
            self.owns_connection = True

        self._ensure_table_exists()

    # ==================================================================
    # SCHEMA + TRIGGERS
    # ==================================================================
    def _ensure_table_exists(self):
        """Create table + triggers if missing."""

        create_table_sql = """
        CREATE TABLE IF NOT EXISTS companies (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

            -- identity
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL UNIQUE,
            location TEXT,
            industry INTEGER,

            -- evidence-based H1B tracking
            sponsorship_cases INTEGER DEFAULT 0,   -- total filings
            approved_cases INTEGER DEFAULT 0,      -- certified approvals

            -- auto-derived fields
            approval_rate NUMERIC DEFAULT 0,
            reliability_score NUMERIC DEFAULT 0,

            -- binary sponsorship decision
            sponsors_visas BOOLEAN DEFAULT FALSE,

            company_url TEXT,
            verified BOOLEAN DEFAULT FALSE,
            notes TEXT,

            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
        """

        # Timestamp trigger
        timestamp_fn = """
        CREATE OR REPLACE FUNCTION update_companies_timestamp_fn()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """

        timestamp_trigger = """
        DROP TRIGGER IF EXISTS trg_update_timestamp ON companies;
        CREATE TRIGGER trg_update_timestamp
        BEFORE UPDATE ON companies
        FOR EACH ROW
        EXECUTE FUNCTION update_companies_timestamp_fn();
        """

        # Rating trigger
        rating_fn = """
        CREATE OR REPLACE FUNCTION update_company_rating()
        RETURNS TRIGGER AS $$
        BEGIN
            -- approval rate
            IF NEW.sponsorship_cases > 0 THEN
                NEW.approval_rate :=
                    NEW.approved_cases::NUMERIC / NEW.sponsorship_cases;
            ELSE
                NEW.approval_rate := 0;
            END IF;

            -- reliability score (0–100)
            NEW.reliability_score :=
                  (0.6 * LEAST(NEW.approved_cases / 10.0, 1.0) * 100)
                + (0.4 * NEW.approval_rate * 100)
                + (CASE WHEN NEW.verified THEN 10 ELSE 0 END);

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """

        rating_trigger = """
        DROP TRIGGER IF EXISTS trg_update_company_rating ON companies;
        CREATE TRIGGER trg_update_company_rating
        BEFORE INSERT OR UPDATE ON companies
        FOR EACH ROW
        EXECUTE FUNCTION update_company_rating();
        """

        try:
            self.cursor.execute(create_table_sql)
            self.cursor.execute(timestamp_fn)
            self.cursor.execute(timestamp_trigger)
            self.cursor.execute(rating_fn)
            self.cursor.execute(rating_trigger)

            # indexes
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_companies_normalized_name ON companies(normalized_name);",
                "CREATE INDEX IF NOT EXISTS idx_companies_sponsors ON companies(sponsors_visas);",
                "CREATE INDEX IF NOT EXISTS idx_companies_cases ON companies(sponsorship_cases DESC);",
            ]
            for idx in indexes:
                self.cursor.execute(idx)

            self.conn.commit()

        except psycopg2.Error as e:
            self.conn.rollback()
            raise RuntimeError(f"DB init error: {e}")

    # ==================================================================
    # HELPERS
    # ==================================================================
    @staticmethod
    def normalize_company_name(name: str) -> str:
        if name is None:
            return ""
        if not isinstance(name, str):
            name = str(name)

        normalized = name.lower().strip()

        for term in CompanyValidation.NORMALIZATION_TERMS:
            normalized = normalized.replace(term, "")

        return " ".join(normalized.split())

    # ==================================================================
    # BULK UPSERT — CORE LOGIC
    # ==================================================================
    def bulk_add_companies(self, companies: List[Dict]) -> int:
        """
        Accepts list of:
            {
                name: str,
                total_cases: int,
                approved_cases: int
            }
        """

        if not companies:
            return 0

        merged = {}

        # merge duplicates
        for c in companies:
            name = c.get("name")
            if not name:
                continue

            norm = self.normalize_company_name(name)
            total = int(c.get("total_cases", 0))
            approved = int(c.get("approved_cases", 0))

            if norm not in merged:
                merged[norm] = {
                    "name": name,
                    "normalized_name": norm,
                    "location": c.get("location"),
                    "industry": c.get("industry"),
                    "company_url": c.get("company_url"),
                    "sponsorship_cases": total,
                    "approved_cases": approved,
                }
            else:
                merged[norm]["sponsorship_cases"] += total
                merged[norm]["approved_cases"] += approved

        # sponsor decision rule
        for c in merged.values():
            c["sponsors_visas"] = (c["approved_cases"] >= 3)

        query = """
        INSERT INTO companies (
            name, normalized_name, location, industry, company_url,
            sponsorship_cases, approved_cases, sponsors_visas
        )
        VALUES %s
        ON CONFLICT (normalized_name) DO UPDATE
        SET
            sponsorship_cases = companies.sponsorship_cases + EXCLUDED.sponsorship_cases,
            approved_cases = companies.approved_cases + EXCLUDED.approved_cases,
            sponsors_visas = (companies.approved_cases + EXCLUDED.approved_cases) >= 3,
            updated_at = NOW();
        """

        data = [
            (
                c["name"],
                c["normalized_name"],
                c["location"],
                c["industry"],
                c["company_url"],
                c["sponsorship_cases"],
                c["approved_cases"],
                c["sponsors_visas"],
            )
            for c in merged.values()
        ]

        try:
            execute_values(self.cursor, query, data, page_size=1000)
            self.conn.commit()
            return self.cursor.rowcount

        except psycopg2.Error as e:
            self.conn.rollback()
            raise RuntimeError(f"Bulk insert failed: {e}")

    # ==================================================================
    # CSV IMPORT (CERTIFIED CASES ONLY)
    # ==================================================================
    def import_from_csv(self, csv_path: str) -> int:
        df = self._load_csv(csv_path)
        if df is None:
            raise RuntimeError("Failed to load CSV file.")

        df = df.rename(columns={
            "Employer (Petitioner) Name": "employer",
            "New Employment Approval": "new_emp_approval",
            "New Employment Denial": "new_emp_denial",
            "Continuation Approval": "cont_approval",
            "Continuation Denial": "cont_denial",
            "Change with Same Employer Approval": "same_emp_approval",
            "Change with Same Employer Denial": "same_emp_denial",
            "New Concurrent Approval": "new_conc_approval",
            "New Concurrent Denial": "new_conc_denial",
            "Change of Employer Approval": "chg_emp_approval",
            "Change of Employer Denial": "chg_emp_denial",
            "Amended Approval": "amd_approval",
            "Amended Denial": "amd_denial",
        })

        approval_cols = [
            "new_emp_approval", "cont_approval", "same_emp_approval",
            "new_conc_approval", "chg_emp_approval", "amd_approval",
        ]

        denial_cols = [
            "new_emp_denial", "cont_denial", "same_emp_denial",
            "new_conc_denial", "chg_emp_denial", "amd_denial",
        ]

        # Convert columns to numeric safely
        for col in approval_cols + denial_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

        df["approved_cases"] = df[approval_cols].sum(axis=1)
        df["total_cases"] = df[approval_cols + denial_cols].sum(axis=1)

        companies = [
            {
                "name": row["employer"],
                "approved_cases": int(row["approved_cases"]),
                "total_cases": int(row["total_cases"]),
            }
            for _, row in df.iterrows()
        ]

        return self.bulk_add_companies(companies)

    # ==================================================================
    # CSV LOADING HELPERS
    # ==================================================================
    def _load_csv(self, path: str) -> Optional[pd.DataFrame]:
        """
        Load USCIS disclosure CSV files.
        Prioritizes UTF-16 + tab-separated (the USCIS standard format).
        Falls back to generic attempts if needed.
        """

        # 1. Try the known USCIS format first (UTF-16 + tab)
        try:
            df = pd.read_csv(
                path,
                encoding="utf-16",
                sep="\t",
                engine="python",   # python engine required for UTF-16 + tabs
                on_bad_lines="skip"
            )
            if len(df.columns) > 1:
                return df
        except Exception as e:
            print("UTF-16 TSV failed:", e)

        # 2. Try fallback encodings/separators (C engine → can use low_memory)
        for encoding in ["utf-8", "latin1"]:
            for sep in ["\t", ",", ";"]:
                try:
                    df = pd.read_csv(
                        path,
                        encoding=encoding,
                        sep=sep,
                        low_memory=False,   # allowed here
                        on_bad_lines="skip"
                    )
                    if len(df.columns) > 1:
                        return df
                except Exception:
                    continue

        return None


    def _filter_sponsorships(self, df: pd.DataFrame) -> pd.DataFrame:
        if VisaConfig.VISA_CLASS_COLUMN in df.columns:
            df = df[
                df[VisaConfig.VISA_CLASS_COLUMN]
                .astype(str)
                .str.contains(VisaConfig.H1B_PATTERN, case=False, na=False)
            ]

        return df

    def _find_employer_column(self, df: pd.DataFrame) -> Optional[str]:
        for col in CSVConfig.EMPLOYER_COLUMNS:
            if col in df.columns:
                return col
        return None

    # ==================================================================
    # READ
    # ==================================================================
    def get_company_by_name(self, name: str):
        norm = self.normalize_company_name(name)
        try:
            self.cursor.execute(
                "SELECT * FROM companies WHERE normalized_name = %s;", (norm,)
            )
            return self.cursor.fetchone()
        except:
            return None

    def get_all_sponsors(self):
        self.cursor.execute("""
            SELECT *
            FROM companies
            WHERE sponsors_visas = TRUE
            ORDER BY approved_cases DESC, reliability_score DESC;
        """)
        return self.cursor.fetchall()

    # ==================================================================
    # CONTEXT MANAGER
    # ==================================================================
    def close(self):
        if self.owns_connection:
            self.cursor.close()
            self.conn.close()

    def __enter__(self): return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.conn.rollback()
        self.close()

if __name__ == "__main__":

    csv_path = Path("resources/Employer_info.csv")
    with CompanyDatabase() as db:
        print(f"Importing from {csv_path}...")
        imported = db.import_from_csv(str(csv_path))

        
