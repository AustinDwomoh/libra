"""
company_db.py - Evidence-based visa sponsorship database.

Tracks:
    total H1B filings
    certified approvals
    approval rate
    reliability score (0–100)
    sponsors_visas boolean (derived from certified evidence)
"""

import math
import re
import time
import requests
import psycopg2
from psycopg2.extras import execute_values
from typing import Optional, List, Dict, Set
from pathlib import Path
import pandas as pd
from rapidfuzz import fuzz, process
from services.config import Config
from collections import Counter
from dataclasses import dataclass
from services.companies import Company
from services.constants import (
    CompanyValidation,
    CSVConfig,
    VisaConfig,
    FuzzyMatchConfig,
)
from services.db_manager import get_db_connection
from services.parentRoslver import ParentBrandResolver

logger = Config.logger


# ======================================================================
# COMPANY DATABASE
# ======================================================================


class CompanyDatabase:
    """
    Database manager for H1B sponsorship data.

    Identity model:
        - raw company names are resolved to a parent brand when confident
        - aggregation happens at the parent-brand level
        - normalization is conservative fallback only
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

        self.resolver = ParentBrandResolver()
        self._ensure_table_exists()

    # ==================================================================
    # SCHEMA + TRIGGERS
    # ==================================================================
    def _ensure_table_exists(self):
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS companies (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

            -- identity
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            parent_brand TEXT,

            location TEXT,
            industry TEXT,

            -- visa evidence
            sponsorship_cases INTEGER DEFAULT 0,
            approved_cases INTEGER DEFAULT 0,

            approval_rate NUMERIC DEFAULT 0,
            reliability_score NUMERIC DEFAULT 0,

            sponsors_visas BOOLEAN DEFAULT FALSE,

            company_url TEXT,
            verified BOOLEAN DEFAULT FALSE,
            notes TEXT,

            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
        """

        timestamp_fn = """
        CREATE OR REPLACE FUNCTION update_companies_timestamp_fn()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """

        rating_fn = """
        CREATE OR REPLACE FUNCTION update_company_rating()
        RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.sponsorship_cases > 0 THEN
                NEW.approval_rate :=
                    NEW.approved_cases::NUMERIC / NEW.sponsorship_cases;
            ELSE
                NEW.approval_rate := 0;
            END IF;

            NEW.reliability_score :=
                  (0.6 * LEAST(NEW.approved_cases / 10.0, 1.0) * 100)
                + (0.4 * NEW.approval_rate * 100)
                + (CASE WHEN NEW.verified THEN 10 ELSE 0 END);

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """

        triggers = """
        DROP TRIGGER IF EXISTS trg_update_timestamp ON companies;
        CREATE TRIGGER trg_update_timestamp
        BEFORE UPDATE ON companies
        FOR EACH ROW EXECUTE FUNCTION update_companies_timestamp_fn();

        DROP TRIGGER IF EXISTS trg_update_company_rating ON companies;
        CREATE TRIGGER trg_update_company_rating
        BEFORE INSERT OR UPDATE ON companies
        FOR EACH ROW EXECUTE FUNCTION update_company_rating();
        """

        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_companies_norm ON companies(normalized_name);",
            "CREATE UNIQUE INDEX IF NOT EXISTS uniq_parent_brand ON companies(parent_brand) WHERE parent_brand IS NOT NULL;",
            "CREATE INDEX IF NOT EXISTS idx_companies_cases ON companies(sponsorship_cases DESC);",
            "CREATE INDEX IF NOT EXISTS idx_companies_sponsors ON companies(sponsors_visas);",
        ]

        try:
            self.cursor.execute(create_table_sql)
            self.cursor.execute(timestamp_fn)
            self.cursor.execute(rating_fn)
            self.cursor.execute(triggers)
            for idx in indexes:
                self.cursor.execute(idx)
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            raise RuntimeError(f"DB init failed: {e}")
    # ==================================================================
    # HELPERS
    # ==================================================================
    @staticmethod
    def normalize_company_name(name: str) -> str:
        
        if name is None:
            return ""

        # Catch pandas NaN / float NaN
        if isinstance(name, float) and math.isnan(name):
            return ""

        # Defensive: coerce everything else to string
        name = str(name).strip()
        if not name:
            return ""
        

        text = re.sub(r"[^\w\s]", " ", name.lower()).strip()
        tokens = [
            t for t in text.split()
            if t not in CompanyValidation.NORMALIZATION_TERMS
        ]
        return " ".join(tokens)
    # ==================================================================
    # BULK UPSERT — CORE LOGIC
    # ==================================================================
    def bulk_add_companies(self, companies: List[Dict]) -> int:
        if not companies:
            return 0

        merged: Dict[str, Dict] = {}

        for row in companies:
            time.sleep(0.05)  # to avoid rate limiting
            raw_name = row.get("name")
            if raw_name is None:
                continue

            # Catch pandas NaN / float NaN
            if isinstance(raw_name, float) and math.isnan(raw_name):
                continue
            # Defensive: coerce everything else to string
            name = str(raw_name).strip()
            if not name:
                continue
            

            resolution = self.resolver.resolve(raw_name)
            print(resolution)
            
            if resolution.parent_brand and resolution.confidence >= 0.8:
                merge_key = resolution.parent_brand.lower()
                display_name = resolution.parent_brand
                parent_brand = resolution.parent_brand
                print(f"Resolved '{raw_name}' → '{parent_brand}' (conf={resolution.confidence:.2f})")
                print(f"Domains: {resolution.domains}")
            else:
                merge_key = self.normalize_company_name(raw_name)
                display_name = raw_name
                parent_brand = None

            total = int(row.get("total_cases", 0))
            approved = int(row.get("approved_cases", 0))

            if merge_key not in merged:
                merged[merge_key] = {
                    "name": display_name,
                    "normalized_name": merge_key,
                    "parent_brand": parent_brand,
                    "sponsorship_cases": total,
                    "approved_cases": approved,
                }
            else:
                merged[merge_key]["sponsorship_cases"] += total
                merged[merge_key]["approved_cases"] += approved

        for m in merged.values():
            m["sponsors_visas"] = m["approved_cases"] >= 3

        query = """
        INSERT INTO companies (
            name,
            normalized_name,
            parent_brand,
            sponsorship_cases,
            approved_cases,
            sponsors_visas
        )
        VALUES %s
        ON CONFLICT (parent_brand)
        DO UPDATE SET
            sponsorship_cases = companies.sponsorship_cases + EXCLUDED.sponsorship_cases,
            approved_cases = companies.approved_cases + EXCLUDED.approved_cases,
            sponsors_visas = (companies.approved_cases + EXCLUDED.approved_cases) >= 3,
            updated_at = NOW();
        """

        data = [
            (
                c["name"],
                c["normalized_name"],
                c["parent_brand"],
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
        except Exception as e:
            self.conn.rollback()
            raise RuntimeError(f"Bulk insert failed: {e}")
    # ==================================================================
    # CSV IMPORT (CERTIFIED CASES ONLY)
    # ==================================================================
    def import_from_csv(self, csv_path: str) -> int:
        df = self._load_csv(csv_path)
        if df is None:
            raise RuntimeError("Failed to load CSV file.")

        df = df.rename(
            columns={
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
            }
        )

        approval_cols = [
            "new_emp_approval",
            "cont_approval",
            "same_emp_approval",
            "new_conc_approval",
            "chg_emp_approval",
            "amd_approval",
        ]

        denial_cols = [
            "new_emp_denial",
            "cont_denial",
            "same_emp_denial",
            "new_conc_denial",
            "chg_emp_denial",
            "amd_denial",
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
                engine="python",  # python engine required for UTF-16 + tabs
                on_bad_lines="skip",
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
                        low_memory=False,  # allowed here
                        on_bad_lines="skip",
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
        self.cursor.execute(
            """
            SELECT *
            FROM companies
            WHERE parent_brand ILIKE %s
               OR normalized_name = %s
            LIMIT 1;
            """,
            (name, norm),
        )
        row = self.cursor.fetchone()
        return Company.from_dict(dict(row)) if row else None

    def get_all_sponsors(self) -> List[Company]:
        self.cursor.execute(
            """
            SELECT *
            FROM companies
            WHERE sponsors_visas = TRUE
            ORDER BY approved_cases DESC, reliability_score DESC;
            """
        )
        return [Company.from_dict(dict(r)) for r in self.cursor.fetchall()]
    
    def get_company_by_id(self, company_id: str):
        try:
            self.cursor.execute("SELECT * FROM companies WHERE id = %s;", (company_id,))
            data = dict(self.cursor.fetchone())
            if data:
                return Company().from_dict(data)
        except:
            return None

    def get_all_sponsors(self):
        self.cursor.execute(
            """
            SELECT *
            FROM companies
            WHERE sponsors_visas = TRUE
            ORDER BY approved_cases DESC, reliability_score DESC;
        """
        )

        sponsors = self.cursor.fetchall()
        return [Company.from_dict(dict(row)) for row in sponsors]

    # ==================================================================
    # CONTEXT MANAGER
    # ==================================================================
    def close(self):
        if self.owns_connection:
            self.cursor.close()
            self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.conn.rollback()
        self.close()




if __name__ == "__main__":
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM companies;")
        conn.commit()
    csv_path = Path("resources/Employer_info.csv")
    with CompanyDatabase() as db:
        print(db.import_from_csv(str(csv_path)))

    