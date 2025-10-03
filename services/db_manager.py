import psycopg2
from psycopg2.extras import RealDictCursor, execute_values
import os
from dotenv import load_dotenv
from typing import Optional, List, Dict, Any
import logging

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_db_connection():
    """Create and return a database connection."""
    try:
        return psycopg2.connect(
            host=os.getenv('DB_HOST'),
            port=os.getenv('DB_PORT'),
            database=os.getenv('DB_NAME'),
            user=os.getenv('DB_USER'),
            password=os.getenv('DB_PASSWORD'),
            cursor_factory=RealDictCursor  # Returns results as dictionaries
        )
    except psycopg2.Error as e:
        logger.error(f"Database connection failed: {e}")
        raise


class JobDatabase:
    """Database manager for job listings."""

    def __init__(self):
        self.conn = get_db_connection()
        self.cursor = self.conn.cursor()

    def close(self):
        """Close database connection."""
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
        logger.debug("Database connection closed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.conn.rollback()
            logger.error(f"Transaction rolled back due to error: {exc_val}")
        self.close()

    def recreate_jobs_table(self):
        """
        Drop and recreate the jobs table with all indexes and triggers.
        Complete fresh start - removes everything and rebuilds from scratch.
        """
        logger.info("Dropping and recreating jobs table from scratch...")
        
        try:
            # Drop table and all dependencies (CASCADE removes triggers, indexes, etc.)
            self.cursor.execute("DROP TABLE IF EXISTS jobs CASCADE;")
            logger.info("✓ Dropped existing table")
            
            # Recreate table
            create_table_sql = """
                CREATE TABLE jobs (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    company TEXT NOT NULL,
                    title TEXT NOT NULL,
                    location TEXT,
                    link TEXT,
                    sponsorship TEXT,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                );
            """
            self.cursor.execute(create_table_sql)
            logger.info("✓ Created jobs table")
            
            # Create indexes
            self.cursor.execute("CREATE INDEX idx_jobs_company ON jobs(company);")
            self.cursor.execute("CREATE INDEX idx_jobs_created_at ON jobs(created_at);")
            logger.info("✓ Created indexes")
            
            # Create update trigger function (CREATE OR REPLACE handles if it exists)
            create_function_sql = """
                CREATE OR REPLACE FUNCTION update_updated_at_column()
                RETURNS TRIGGER AS $$
                BEGIN
                    NEW.updated_at = NOW();
                    RETURN NEW;
                END;
                $$ language 'plpgsql';
            """
            self.cursor.execute(create_function_sql)
            logger.info("✓ Created trigger function")
            
            # Create trigger
            create_trigger_sql = """
                CREATE TRIGGER update_jobs_updated_at 
                BEFORE UPDATE ON jobs
                FOR EACH ROW 
                EXECUTE FUNCTION update_updated_at_column();
            """
            self.cursor.execute(create_trigger_sql)
            logger.info("✓ Created trigger")
            
            self.conn.commit()
            logger.info("✓ Table recreation complete!")
            
        except psycopg2.Error as e:
            self.conn.rollback()
            logger.error(f"Error recreating table: {e}")
            raise

    def refresh_all_jobs(self, jobs: List[Dict[str, Any]]) -> Dict[str, int]:
        """
        Drop table, recreate from scratch, then insert all jobs.
        Nuclear option - complete fresh start every time.
        
        Returns dict with 'inserted' count.
        """
        if not jobs:
            logger.warning("No jobs provided to refresh")
            return {'inserted': 0}
        
        try:
            # Drop and recreate entire table structure
            self.recreate_jobs_table()
            
            logger.info(f"Inserting {len(jobs)} new jobs into fresh table...")
            
            # Insert all jobs
            query = """
                INSERT INTO jobs (company, title, location, link, sponsorship)
                VALUES %s;
            """
            data = [(j.get('company'), j.get('title'), j.get('location'),
                     j.get('link'), j.get('sponsorship')) for j in jobs]
            
            execute_values(self.cursor, query, data, page_size=1000)
            inserted_count = self.cursor.rowcount
            
            self.conn.commit()
            
            logger.info(f"✓ Refresh completed: Inserted {inserted_count} jobs into brand new table")
            
            return {'inserted': inserted_count}
            
        except psycopg2.Error as e:
            self.conn.rollback()
            logger.error(f"Error during refresh: {e}")
            raise

    # CREATE
    def insert_job(self, company: str, title: str, location: str = None,
                   link: str = None, sponsorship: str = None) -> str:
        """Insert a new job and return its ID."""
        query = """
            INSERT INTO jobs (company, title, location, link, sponsorship)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id;
        """
        try:
            self.cursor.execute(query, (company, title, location, link, sponsorship))
            self.conn.commit()
            return self.cursor.fetchone()['id']
        except psycopg2.Error as e:
            self.conn.rollback()
            logger.error(f"Error inserting job: {e}")
            raise

    def insert_jobs_bulk(self, jobs: List[Dict[str, Any]]) -> int:
        """Insert multiple jobs at once. Returns number of inserted rows."""
        if not jobs:
            logger.warning("No jobs to insert")
            return 0
            
        logger.info(f"Inserting {len(jobs)} jobs into the database...")
        query = """
            INSERT INTO jobs (company, title, location, link, sponsorship)
            VALUES %s
            ON CONFLICT (link) DO UPDATE
            SET company = EXCLUDED.company,
                title = EXCLUDED.title,
                location = EXCLUDED.location,
                sponsorship = EXCLUDED.sponsorship,
                updated_at = NOW();
            """

        data = [(j.get('company'), j.get('title'), j.get('location'),
                 j.get('link'), j.get('sponsorship')) for j in jobs]

        try:
            execute_values(self.cursor, query, data, page_size=1000)
            self.conn.commit()
            logger.info(f"Bulk insert completed. {self.cursor.rowcount} jobs processed.")
            return self.cursor.rowcount
        except psycopg2.Error as e:
            self.conn.rollback()
            logger.error(f"Error during bulk insert: {e}")
            raise

    # READ - Single Entry
    def get_job_by_id(self, job_id: str) -> Optional[Dict]:
        """Get a single job by ID."""
        query = "SELECT * FROM jobs WHERE id = %s;"
        try:
            self.cursor.execute(query, (job_id,))
            return self.cursor.fetchone()
        except psycopg2.Error as e:
            logger.error(f"Error fetching job by id: {e}")
            raise

    def get_job_by_title(self, title: str) -> Optional[Dict]:
        """Get first job matching exact title."""
        query = "SELECT * FROM jobs WHERE title = %s LIMIT 1;"
        try:
            self.cursor.execute(query, (title,))
            return self.cursor.fetchone()
        except psycopg2.Error as e:
            logger.error(f"Error fetching job by title: {e}")
            raise

    # READ - Multiple Entries
    def get_all_jobs(self, limit: int = None) -> List[Dict]:
        """Get all jobs, optionally limited."""
        query = "SELECT * FROM jobs ORDER BY created_at DESC"
        if limit:
            query += f" LIMIT {limit};"
        try:
            self.cursor.execute(query)
            return self.cursor.fetchall()
        except psycopg2.Error as e:
            logger.error(f"Error fetching all jobs: {e}")
            raise

    def get_jobs_by_company(self, company: str) -> List[Dict]:
        """Get all jobs from a specific company."""
        query = "SELECT * FROM jobs WHERE company = %s ORDER BY created_at DESC;"
        try:
            self.cursor.execute(query, (company,))
            return self.cursor.fetchall()
        except psycopg2.Error as e:
            logger.error(f"Error fetching jobs by company: {e}")
            raise

    def search_jobs(self, keyword: str) -> List[Dict]:
        """Search jobs by keyword in all relevant fields except link."""
        query = """
            SELECT * FROM jobs
            WHERE title ILIKE %s
            OR company ILIKE %s
            OR location ILIKE %s
            OR sponsorship ILIKE %s
            ORDER BY created_at DESC;
        """
        search_pattern = f"%{keyword}%"
        params = (search_pattern, search_pattern, search_pattern, search_pattern)

        try:
            self.cursor.execute(query, params)
            return self.cursor.fetchall()
        except psycopg2.Error as e:
            logger.error(f"Error searching jobs: {e}")
            raise


    def get_jobs_with_sponsorship(self, sponsorship: str = "Likely sponsorship") -> List[Dict]:
        """Get jobs filtered by sponsorship status."""
        try:
            if sponsorship:
                query = "SELECT * FROM jobs WHERE sponsorship = %s ORDER BY created_at DESC;"
                self.cursor.execute(query, (sponsorship,))
            else:
                query = "SELECT * FROM jobs WHERE sponsorship IS NOT NULL ORDER BY created_at DESC;"
                self.cursor.execute(query)
            return self.cursor.fetchall()
        except psycopg2.Error as e:
            logger.error(f"Error fetching jobs with sponsorship: {e}")
            raise

    # UPDATE
    def update_job(self, job_id: str, **kwargs) -> bool:
        """Update job fields. Pass fields as keyword arguments."""
        allowed_fields = ['company', 'title', 'location', 'link', 'sponsorship']
        updates = {k: v for k, v in kwargs.items() if k in allowed_fields}

        if not updates:
            logger.warning("No valid fields provided for update")
            return False

        set_clause = ", ".join([f"{field} = %s" for field in updates.keys()])
        query = f"UPDATE jobs SET {set_clause} WHERE id = %s;"

        values = list(updates.values()) + [job_id]
        try:
            self.cursor.execute(query, values)
            self.conn.commit()
            return self.cursor.rowcount > 0
        except psycopg2.Error as e:
            self.conn.rollback()
            logger.error(f"Error updating job: {e}")
            raise

    # DELETE
    def delete_job(self, job_id: str) -> bool:
        """Delete a job by ID."""
        query = "DELETE FROM jobs WHERE id = %s;"
        try:
            self.cursor.execute(query, (job_id,))
            self.conn.commit()
            return self.cursor.rowcount > 0
        except psycopg2.Error as e:
            self.conn.rollback()
            logger.error(f"Error deleting job: {e}")
            raise

    def delete_jobs_by_company(self, company: str) -> int:
        """Delete all jobs from a company. Returns number of deleted rows."""
        query = "DELETE FROM jobs WHERE company = %s;"
        try:
            self.cursor.execute(query, (company,))
            self.conn.commit()
            return self.cursor.rowcount
        except psycopg2.Error as e:
            self.conn.rollback()
            logger.error(f"Error deleting jobs by company: {e}")
            raise

    def delete_all_jobs(self) -> int:
        """Delete all jobs. Returns number of deleted rows."""
        query = "DELETE FROM jobs;"
        try:
            self.cursor.execute(query)
            self.conn.commit()
            logger.info(f"Deleted {self.cursor.rowcount} jobs")
            return self.cursor.rowcount
        except psycopg2.Error as e:
            self.conn.rollback()
            logger.error(f"Error deleting all jobs: {e}")
            raise

    # COUNT
    def count_jobs(self) -> int:
        """Get total number of jobs."""
        query = "SELECT COUNT(*) as count FROM jobs;"
        try:
            self.cursor.execute(query)
            return self.cursor.fetchone()['count']
        except psycopg2.Error as e:
            logger.error(f"Error counting jobs: {e}")
            raise

    def count_jobs_by_company(self, company: str) -> int:
        """Get number of jobs for a specific company."""
        query = "SELECT COUNT(*) as count FROM jobs WHERE company = %s;"
        try:
            self.cursor.execute(query, (company,))
            return self.cursor.fetchone()['count']
        except psycopg2.Error as e:
            logger.error(f"Error counting jobs by company: {e}")
            raise


# Example usage
if __name__ == "__main__":
    # Using context manager (recommended)
    with JobDatabase() as db:
        # Simulate scraped jobs
        new_jobs = [
            {
                "company": "Google",
                "title": "Software Engineer Intern",
                "location": "New York, NY",
                "link": "https://example.com/job1",
                "sponsorship": "Likely sponsorship"
            },
            {
                "company": "Meta",
                "title": "Data Scientist Intern",
                "location": "Menlo Park, CA",
                "link": "https://example.com/job2",
                "sponsorship": "No record found"
            }
        ]
        
        # Refresh all jobs (drop table, recreate, insert new)
        result = db.refresh_all_jobs(new_jobs)
        print(f"Refresh complete: {result}")
        
        # Count total jobs
        total = db.count_jobs()
        print(f"Total jobs in database: {total}")