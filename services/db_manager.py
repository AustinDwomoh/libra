import psycopg2
from psycopg2.extras import RealDictCursor, execute_values
from config import Config
from typing import Optional, List, Dict, Any

logger = Config.logger
def get_db_connection():
    """
    Create and return a database connection.
    """
    try:
        connection = psycopg2.connect(
            host=Config.DB_HOST,
            port=Config.DB_PORT,
            database=Config.DB_NAME,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            cursor_factory=RealDictCursor
        )
        logger.info("Connected to PRODUCTION database")

        
        return connection
        
    except psycopg2.Error as e:
        logger.error(f"Database connection failed: {e}")
        raise


class JobDatabase:
    """Database manager for job listings with multi-source support."""

    def __init__(self, auto_setup=True):
        """
        Initialize database connection.
        
        Args:
            auto_setup: If True, ensure table exists and is up-to-date
        """
        self.conn = get_db_connection()
        self.cursor = self.conn.cursor()
        
        if auto_setup:
            self._ensure_table_ready()

    def _ensure_table_ready(self):
        """
        Internal method: Ensure table exists with correct schema.
        Creates table if missing, migrates if schema is outdated.
        """
        try:
            # First, create table if it doesn't exist
            self._create_jobs_table_if_not_exists()
            
            # Then check if it needs migration
            self.cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'jobs' AND column_name = 'source';
            """)
            
            if not self.cursor.fetchone():
                logger.info("Old schema detected. Running migration...")
                self.migrate_jobs_table()
                
        except psycopg2.Error as e:
            logger.warning(f"Could not verify table status: {e}")

    def _create_jobs_table_if_not_exists(self):
        """Internal method: Create jobs table only if it doesn't exist."""
        try:
            create_table_sql = """
                CREATE TABLE IF NOT EXISTS jobs (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    company TEXT NOT NULL,
                    title TEXT NOT NULL,
                    location TEXT,
                    link TEXT UNIQUE,
                    sponsorship TEXT,
                    source TEXT DEFAULT 'simplify',
                    remote BOOLEAN DEFAULT FALSE,
                    date_posted TIMESTAMP,
                    description TEXT,
                    tags TEXT[],
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                );
            """
            self.cursor.execute(create_table_sql)
            
            # Create indexes
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company);",
                "CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source);",
                "CREATE INDEX IF NOT EXISTS idx_jobs_sponsorship ON jobs(sponsorship);",
                "CREATE INDEX IF NOT EXISTS idx_jobs_remote ON jobs(remote);",
                "CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at);",
                "CREATE INDEX IF NOT EXISTS idx_jobs_link ON jobs(link);"
            ]
            
            for idx in indexes:
                self.cursor.execute(idx)
            
            # Create trigger function and trigger
            self.cursor.execute("""
                CREATE OR REPLACE FUNCTION update_updated_at_column()
                RETURNS TRIGGER AS $$
                BEGIN
                    NEW.updated_at = NOW();
                    RETURN NEW;
                END;
                $$ language 'plpgsql';
            """)
            
            self.cursor.execute("""
                DROP TRIGGER IF EXISTS update_jobs_updated_at ON jobs;
                CREATE TRIGGER update_jobs_updated_at 
                BEFORE UPDATE ON jobs
                FOR EACH ROW 
                EXECUTE FUNCTION update_updated_at_column();
            """)
            
            self.conn.commit()
            
        except psycopg2.Error as e:
            self.conn.rollback()
            logger.error(f"Error creating table: {e}")
            raise

    def migrate_jobs_table(self):
        """
        Migrate existing jobs table to new structure WITHOUT losing data.
        Safe to run multiple times.
        
        KEEP THIS: Critical for users upgrading from old schema to new one.
        Without this, they'd have to manually run SQL or lose all their data.
        """
        logger.info("=" * 60)
        logger.info("MIGRATING DATABASE SCHEMA")
        logger.info("=" * 60)
        
        try:
            migrations = [
                ("Adding 'source' column", 
                 "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'simplify';"),
                
                ("Adding 'remote' column", 
                 "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS remote BOOLEAN DEFAULT FALSE;"),
                
                ("Adding 'date_posted' column", 
                 "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS date_posted TIMESTAMP;"),
                
                ("Adding 'description' column", 
                 "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS description TEXT;"),
                
                ("Adding 'tags' column", 
                 "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS tags TEXT[];"),
                
                ("Adding UNIQUE constraint on link", 
                 """
                 DO $$ 
                 BEGIN
                     IF NOT EXISTS (
                         SELECT 1 FROM pg_constraint 
                         WHERE conname = 'jobs_link_key' AND conrelid = 'jobs'::regclass
                     ) THEN
                         ALTER TABLE jobs ADD CONSTRAINT jobs_link_key UNIQUE (link);
                     END IF;
                 END $$;
                 """),
                
                ("Creating index on 'source'", 
                 "CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source);"),
                
                ("Creating index on 'remote'", 
                 "CREATE INDEX IF NOT EXISTS idx_jobs_remote ON jobs(remote);"),
                
                ("Creating index on 'link'", 
                 "CREATE INDEX IF NOT EXISTS idx_jobs_link ON jobs(link);"),
                
                ("Creating index on 'sponsorship'", 
                 "CREATE INDEX IF NOT EXISTS idx_jobs_sponsorship ON jobs(sponsorship);")
            ]
            
            for description, sql in migrations:
                logger.info(f"  {description}...")
                self.cursor.execute(sql)
            
            self.conn.commit()
            
            logger.info("=" * 60)
            logger.info("✓ MIGRATION COMPLETED")
            logger.info("=" * 60)
            
        except psycopg2.Error as e:
            self.conn.rollback()
            logger.error(f"Migration failed: {e}")
            raise

    def recreate_jobs_table(self):
        """
        Drop and recreate the jobs table from scratch.
        WARNING: This deletes all existing data.
        
        KEEP THIS: Useful for:
        - Development/testing (quick reset)
        - Fixing corrupted tables
        - Starting fresh when you have a backup
        - When migration fails and you need nuclear option
        
        It's a power tool - dangerous but sometimes necessary.
        """
        logger.warning("⚠️  DROPPING ALL DATA AND RECREATING TABLE...")
        
        try:
            self.cursor.execute("DROP TABLE IF EXISTS jobs CASCADE;")
            logger.info("✓ Dropped existing table")
            
            # Reuse the create logic
            self._create_jobs_table_if_not_exists()
            
            logger.info("✓ Table recreation complete!")
            
        except psycopg2.Error as e:
            self.conn.rollback()
            logger.error(f"Error recreating table: {e}")
            raise

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

    # CREATE
    def insert_job(self, company: str, title: str, location: str = None,
                   link: str = None, sponsorship: str = None, source: str = 'simplify',
                   remote: bool = False, date_posted = None, description: str = None,
                   tags: List[str] = None) -> str:
        """Insert a new job and return its ID."""
        query = """
            INSERT INTO jobs (
                company, title, location, link, sponsorship, 
                source, remote, date_posted, description, tags
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id;
        """
        try:
            self.cursor.execute(query, (
                company, title, location, link, sponsorship,
                source, remote, date_posted, description, tags or []
            ))
            self.conn.commit()
            return self.cursor.fetchone()['id']
        except psycopg2.Error as e:
            self.conn.rollback()
            logger.error(f"Error inserting job: {e}")
            raise

    def insert_jobs_bulk(self, jobs: List[Dict[str, Any]]) -> int:
        """
        Insert multiple jobs at once. Returns number of inserted/updated rows.
        Uses UPSERT to handle duplicates gracefully.
        """
        if not jobs:
            logger.warning("No jobs to insert")
            return 0
            
        logger.info(f"Inserting {len(jobs)} jobs into the database...")
        query = """
            INSERT INTO jobs (
                company, title, location, link, sponsorship,
                source, remote, date_posted, description, tags
            )
            VALUES %s
            ON CONFLICT (link) DO UPDATE
            SET company = EXCLUDED.company,
                title = EXCLUDED.title,
                location = EXCLUDED.location,
                sponsorship = EXCLUDED.sponsorship,
                source = EXCLUDED.source,
                remote = EXCLUDED.remote,
                date_posted = EXCLUDED.date_posted,
                description = EXCLUDED.description,
                tags = EXCLUDED.tags,
                updated_at = NOW();
        """

        data = [
            (
                j.get('company'), 
                j.get('title'), 
                j.get('location'),
                j.get('link'), 
                j.get('sponsorship'),
                j.get('source', 'simplify'),
                j.get('remote', False),
                j.get('date_posted'),
                j.get('description'),
                j.get('tags', [])
            )
            for j in jobs
        ]

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

    def get_jobs_by_source(self, source: str) -> List[Dict]:
        """Get all jobs from a specific source (simplify, jsearch, remoteok)."""
        query = "SELECT * FROM jobs WHERE source = %s ORDER BY created_at DESC;"
        try:
            self.cursor.execute(query, (source,))
            return self.cursor.fetchall()
        except psycopg2.Error as e:
            logger.error(f"Error fetching jobs by source: {e}")
            raise

    def get_remote_jobs(self) -> List[Dict]:
        """Get all remote jobs."""
        query = "SELECT * FROM jobs WHERE remote = TRUE ORDER BY created_at DESC;"
        try:
            self.cursor.execute(query)
            return self.cursor.fetchall()
        except psycopg2.Error as e:
            logger.error(f"Error fetching remote jobs: {e}")
            raise

    def search_jobs(self, keyword: str) -> List[Dict]:
        """Search jobs by keyword in all relevant fields."""
        query = """
            SELECT * FROM jobs
            WHERE title ILIKE %s
            OR company ILIKE %s
            OR location ILIKE %s
            OR sponsorship ILIKE %s
            OR description ILIKE %s
            ORDER BY created_at DESC;
        """
        search_pattern = f"%{keyword}%"
        params = (search_pattern, search_pattern, search_pattern, 
                  search_pattern, search_pattern)

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

    def get_jobs_filtered(self, source: str = None, remote: bool = None, 
                          sponsorship: str = None, limit: int = None) -> List[Dict]:
        """
        Get jobs with flexible filtering options.
        
        KEEP THIS: Essential for your frontend to filter jobs.
        Much more efficient than fetching all and filtering in Python.
        """
        query = "SELECT * FROM jobs WHERE 1=1"
        params = []
        
        if source:
            query += " AND source = %s"
            params.append(source)
        
        if remote is not None:
            query += " AND remote = %s"
            params.append(remote)
        
        if sponsorship:
            query += " AND sponsorship = %s"
            params.append(sponsorship)
        
        query += " ORDER BY created_at DESC"
        
        if limit:
            query += f" LIMIT {limit}"
        
        query += ";"
        
        try:
            self.cursor.execute(query, params)
            return self.cursor.fetchall()
        except psycopg2.Error as e:
            logger.error(f"Error fetching filtered jobs: {e}")
            raise

    # UPDATE
    def update_job(self, job_id: str, **kwargs) -> bool:
        """
        Update job fields. Pass fields as keyword arguments.
        
        KEEP THIS: Needed when you implement application tracking.
        You'll want to mark jobs as "applied" or update their status.
        """
        allowed_fields = ['company', 'title', 'location', 'link', 'sponsorship',
                          'source', 'remote', 'date_posted', 'description', 'tags']
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
        """
        Delete a job by ID.
        
        KEEP THIS: For when job postings close or you want to clean up manually.
        """
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

    def delete_jobs_by_source(self, source: str) -> int:
        """
        Delete all jobs from a specific source.
        
        KEEP THIS: Useful if one source starts giving bad data.
        E.g., "RemoteOK started scraping wrong, delete all remoteok jobs"
        """
        query = "DELETE FROM jobs WHERE source = %s;"
        try:
            self.cursor.execute(query, (source,))
            self.conn.commit()
            logger.info(f"Deleted {self.cursor.rowcount} jobs from source: {source}")
            return self.cursor.rowcount
        except psycopg2.Error as e:
            self.conn.rollback()
            logger.error(f"Error deleting jobs by source: {e}")
            raise

    def delete_all_jobs(self) -> int:
        """
        Delete all jobs.
        
        KEEP THIS: For testing or when you want to refresh all data.
        Safer than DROP TABLE because it keeps the schema.
        """
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

    # COUNT & STATISTICS
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

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get comprehensive statistics about jobs in database.
        
        KEEP THIS: Perfect for your dashboard/analytics.
        Shows breakdown by source, sponsorship, remote, etc.
        """
        stats_query = """
            SELECT 
                COUNT(*) as total_jobs,
                COUNT(*) FILTER (WHERE sponsorship = 'Likely sponsorship') as with_sponsorship,
                COUNT(*) FILTER (WHERE remote = TRUE) as remote_jobs,
                COUNT(*) FILTER (WHERE source = 'simplify') as from_simplify,
                COUNT(*) FILTER (WHERE source = 'jsearch') as from_jsearch,
                COUNT(*) FILTER (WHERE source = 'remoteok') as from_remoteok,
                COUNT(DISTINCT company) as unique_companies
            FROM jobs;
        """
        try:
            self.cursor.execute(stats_query)
            return self.cursor.fetchone()
        except psycopg2.Error as e:
            logger.error(f"Error getting statistics: {e}")
            raise


# Test/Demo usage
if __name__ == "__main__":
    with JobDatabase() as db:
        stats = db.get_statistics()
        print(f"\nDatabase Statistics:")
        print(f"  Total jobs: {stats['total_jobs']}")
        print(f"  With sponsorship: {stats['with_sponsorship']}")
        print(f"  From Simplify: {stats['from_simplify']}")
        print(f"  From JSearch: {stats['from_jsearch']}")
        print(f"  From RemoteOK: {stats['from_remoteok']}")
        print(f"  Remote jobs: {stats['remote_jobs']}")
        print(f"  Unique companies: {stats['unique_companies']}")