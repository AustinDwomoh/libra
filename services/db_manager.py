"""
db_manager.py - Refactored with constants

Key improvements:
- Replaced ALL magic strings with named constants
- Used DBFields class for column names
- Used JobSource enum for source values
- Used SponsorshipStatus for sponsorship values
- Extracted SQL queries to methods
- Better type hints throughout
"""
import psycopg2
from psycopg2.extras import RealDictCursor, execute_values
from services.config import Config
from typing import Optional, List, Dict, Any

from services.constants import (
    DBFields,
    JobSource,
    SponsorshipStatus,
    Defaults
)

logger = Config.logger


def get_db_connection():
    """Create and return a database connection"""
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
    """Database manager for job listings with multi-source support"""

    # Table and trigger names
    TABLE_NAME = "jobs"
    TRIGGER_FUNCTION_NAME = "update_updated_at_column"
    TRIGGER_NAME = "update_jobs_updated_at"
    
    # Constraint names
    LINK_UNIQUE_CONSTRAINT = "jobs_link_key"
    
    # Default values for queries
    DEFAULT_SOURCE = JobSource.SIMPLIFY.value
    DEFAULT_PAGE_SIZE = 1000

    def __init__(self, auto_setup: bool = True):
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
        Ensure table exists with correct schema.
        Creates table if missing, migrates if schema is outdated.
        """
        try:
            self._create_jobs_table_if_not_exists()

            # Check if 'source' column exists (indicator of new schema)
            self.cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = %s AND column_name = %s;
            """, (self.TABLE_NAME, DBFields.SOURCE))
            
            if not self.cursor.fetchone():
                logger.info("Old schema detected. Running migration...")
                self.migrate_jobs_table()
                
        except psycopg2.Error as e:
            logger.warning(f"Could not verify table status: {e}")

    def _create_jobs_table_if_not_exists(self):
        """Create jobs table only if it doesn't exist"""
        try:
            create_table_sql = f"""
                CREATE TABLE IF NOT EXISTS {self.TABLE_NAME} (
                    {DBFields.ID} UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    {DBFields.COMPANY} TEXT NOT NULL,
                    {DBFields.TITLE} TEXT NOT NULL,
                    {DBFields.LOCATION} TEXT,
                    {DBFields.LINK} TEXT UNIQUE,
                    {DBFields.SPONSORSHIP} TEXT,
                    {DBFields.SOURCE} TEXT DEFAULT %s,
                    {DBFields.REMOTE} BOOLEAN DEFAULT FALSE,
                    {DBFields.DATE_POSTED} TIMESTAMP,
                    {DBFields.DESCRIPTION} TEXT,
                    {DBFields.TAGS} TEXT[],
                    {DBFields.CREATED_AT} TIMESTAMP DEFAULT NOW(),
                    {DBFields.UPDATED_AT} TIMESTAMP DEFAULT NOW()
                );
            """
            self.cursor.execute(create_table_sql, (self.DEFAULT_SOURCE,))
            
            # Create indexes
            self._create_indexes()
            
            # Create trigger function and trigger
            self._create_update_trigger()
            
            self.conn.commit()
            
        except psycopg2.Error as e:
            self.conn.rollback()
            logger.error(f"Error creating table: {e}")
            raise

    def _create_indexes(self):
        """Create indexes for performance"""
        indexes = [
            f"CREATE INDEX IF NOT EXISTS idx_jobs_company ON {self.TABLE_NAME}({DBFields.COMPANY});",
            f"CREATE INDEX IF NOT EXISTS idx_jobs_source ON {self.TABLE_NAME}({DBFields.SOURCE});",
            f"CREATE INDEX IF NOT EXISTS idx_jobs_sponsorship ON {self.TABLE_NAME}({DBFields.SPONSORSHIP});",
            f"CREATE INDEX IF NOT EXISTS idx_jobs_remote ON {self.TABLE_NAME}({DBFields.REMOTE});",
            f"CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON {self.TABLE_NAME}({DBFields.CREATED_AT});",
            f"CREATE INDEX IF NOT EXISTS idx_jobs_link ON {self.TABLE_NAME}({DBFields.LINK});",
        ]
        
        for idx in indexes:
            self.cursor.execute(idx)

    def _create_update_trigger(self):
        """Create trigger to auto-update updated_at timestamp"""
        self.cursor.execute(f"""
            CREATE OR REPLACE FUNCTION {self.TRIGGER_FUNCTION_NAME}()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.{DBFields.UPDATED_AT} = NOW();
                RETURN NEW;
            END;
            $$ language 'plpgsql';
        """)
        
        self.cursor.execute(f"""
            DROP TRIGGER IF EXISTS {self.TRIGGER_NAME} ON {self.TABLE_NAME};
            CREATE TRIGGER {self.TRIGGER_NAME}
            BEFORE UPDATE ON {self.TABLE_NAME}
            FOR EACH ROW 
            EXECUTE FUNCTION {self.TRIGGER_FUNCTION_NAME}();
        """)

    def migrate_jobs_table(self):
        """
        Migrate existing jobs table to new structure WITHOUT losing data.
        Safe to run multiple times.
        """
        logger.info("=" * 60)
        logger.info("MIGRATING DATABASE SCHEMA")
        logger.info("=" * 60)
        
        try:
            migrations = [
                (f"Adding '{DBFields.SOURCE}' column", 
                 f"ALTER TABLE {self.TABLE_NAME} ADD COLUMN IF NOT EXISTS {DBFields.SOURCE} TEXT DEFAULT %s;",
                 (self.DEFAULT_SOURCE,)),
                
                (f"Adding '{DBFields.REMOTE}' column", 
                 f"ALTER TABLE {self.TABLE_NAME} ADD COLUMN IF NOT EXISTS {DBFields.REMOTE} BOOLEAN DEFAULT FALSE;",
                 None),
                
                (f"Adding '{DBFields.DATE_POSTED}' column", 
                 f"ALTER TABLE {self.TABLE_NAME} ADD COLUMN IF NOT EXISTS {DBFields.DATE_POSTED} TIMESTAMP;",
                 None),
                
                (f"Adding '{DBFields.DESCRIPTION}' column", 
                 f"ALTER TABLE {self.TABLE_NAME} ADD COLUMN IF NOT EXISTS {DBFields.DESCRIPTION} TEXT;",
                 None),
                
                (f"Adding '{DBFields.TAGS}' column", 
                 f"ALTER TABLE {self.TABLE_NAME} ADD COLUMN IF NOT EXISTS {DBFields.TAGS} TEXT[];",
                 None),
                
                (f"Adding UNIQUE constraint on {DBFields.LINK}", 
                 f"""
                 DO $$ 
                 BEGIN
                     IF NOT EXISTS (
                         SELECT 1 FROM pg_constraint 
                         WHERE conname = %s AND conrelid = %s::regclass
                     ) THEN
                         ALTER TABLE {self.TABLE_NAME} ADD CONSTRAINT {self.LINK_UNIQUE_CONSTRAINT} UNIQUE ({DBFields.LINK});
                     END IF;
                 END $$;
                 """,
                 (self.LINK_UNIQUE_CONSTRAINT, self.TABLE_NAME)),
            ]
            
            # Add index creation migrations
            index_migrations = [
                (f"Creating index on '{DBFields.SOURCE}'", 
                 f"CREATE INDEX IF NOT EXISTS idx_jobs_source ON {self.TABLE_NAME}({DBFields.SOURCE});",
                 None),
                
                (f"Creating index on '{DBFields.REMOTE}'", 
                 f"CREATE INDEX IF NOT EXISTS idx_jobs_remote ON {self.TABLE_NAME}({DBFields.REMOTE});",
                 None),
                
                (f"Creating index on '{DBFields.LINK}'", 
                 f"CREATE INDEX IF NOT EXISTS idx_jobs_link ON {self.TABLE_NAME}({DBFields.LINK});",
                 None),
                
                (f"Creating index on '{DBFields.SPONSORSHIP}'", 
                 f"CREATE INDEX IF NOT EXISTS idx_jobs_sponsorship ON {self.TABLE_NAME}({DBFields.SPONSORSHIP});",
                 None),
            ]
            
            migrations.extend(index_migrations)
            
            for description, sql, params in migrations:
                logger.info(f"  {description}...")
                if params:
                    self.cursor.execute(sql, params)
                else:
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
        """
        logger.warning("⚠️  DROPPING ALL DATA AND RECREATING TABLE...")
        
        try:
            self.cursor.execute(f"DROP TABLE IF EXISTS {self.TABLE_NAME} CASCADE;")
            logger.info("✓ Dropped existing table")
            
            self._create_jobs_table_if_not_exists()
            
            logger.info("✓ Table recreation complete!")
            
        except psycopg2.Error as e:
            self.conn.rollback()
            logger.error(f"Error recreating table: {e}")
            raise

    def close(self):
        """Close database connection"""
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
    def insert_job(
        self, 
        company: str, 
        title: str, 
        location: Optional[str] = None,
        link: Optional[str] = None, 
        sponsorship: Optional[str] = None, 
        source: str = None,
        remote: bool = False, 
        date_posted: Optional[str] = None, 
        description: Optional[str] = None,
        tags: Optional[List[str]] = None
    ) -> str:
        """Insert a new job and return its ID"""
        source = source or self.DEFAULT_SOURCE
        
        query = f"""
            INSERT INTO {self.TABLE_NAME} (
                {DBFields.COMPANY}, {DBFields.TITLE}, {DBFields.LOCATION}, 
                {DBFields.LINK}, {DBFields.SPONSORSHIP}, {DBFields.SOURCE}, 
                {DBFields.REMOTE}, {DBFields.DATE_POSTED}, {DBFields.DESCRIPTION}, 
                {DBFields.TAGS}
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {DBFields.ID};
        """
        try:
            self.cursor.execute(query, (
                company, title, location, link, sponsorship,
                source, remote, date_posted, description, tags or []
            ))
            self.conn.commit()
            return self.cursor.fetchone()[DBFields.ID]
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
        
        query = f"""
            INSERT INTO {self.TABLE_NAME} (
                {DBFields.COMPANY}, {DBFields.TITLE}, {DBFields.LOCATION}, 
                {DBFields.LINK}, {DBFields.SPONSORSHIP}, {DBFields.SOURCE}, 
                {DBFields.REMOTE}, {DBFields.DATE_POSTED}, {DBFields.DESCRIPTION}, 
                {DBFields.TAGS}
            )
            VALUES %s
            ON CONFLICT ({DBFields.LINK}) DO UPDATE
            SET {DBFields.COMPANY} = EXCLUDED.{DBFields.COMPANY},
                {DBFields.TITLE} = EXCLUDED.{DBFields.TITLE},
                {DBFields.LOCATION} = EXCLUDED.{DBFields.LOCATION},
                {DBFields.SPONSORSHIP} = EXCLUDED.{DBFields.SPONSORSHIP},
                {DBFields.SOURCE} = EXCLUDED.{DBFields.SOURCE},
                {DBFields.REMOTE} = EXCLUDED.{DBFields.REMOTE},
                {DBFields.DATE_POSTED} = EXCLUDED.{DBFields.DATE_POSTED},
                {DBFields.DESCRIPTION} = EXCLUDED.{DBFields.DESCRIPTION},
                {DBFields.TAGS} = EXCLUDED.{DBFields.TAGS},
                {DBFields.UPDATED_AT} = NOW();
        """

        data = [
            (
                j.get(DBFields.COMPANY), 
                j.get(DBFields.TITLE), 
                j.get(DBFields.LOCATION),
                j.get(DBFields.LINK), 
                j.get(DBFields.SPONSORSHIP),
                j.get(DBFields.SOURCE, self.DEFAULT_SOURCE),
                j.get(DBFields.REMOTE, False),
                j.get(DBFields.DATE_POSTED),
                j.get(DBFields.DESCRIPTION),
                j.get(DBFields.TAGS, [])
            )
            for j in jobs
        ]

        try:
            execute_values(self.cursor, query, data, page_size=self.DEFAULT_PAGE_SIZE)
            self.conn.commit()
            logger.info(f"Bulk insert completed. {self.cursor.rowcount} jobs processed.")
            return self.cursor.rowcount
        except psycopg2.Error as e:
            self.conn.rollback()
            logger.error(f"Error during bulk insert: {e}")
            raise

    # READ - Single Entry
    def get_job_by_id(self, job_id: str) -> Optional[Dict]:
        """Get a single job by ID"""
        query = f"SELECT * FROM {self.TABLE_NAME} WHERE {DBFields.ID} = %s;"
        try:
            self.cursor.execute(query, (job_id,))
            return self.cursor.fetchone()
        except psycopg2.Error as e:
            logger.error(f"Error fetching job by id: {e}")
            raise

    def get_job_by_title(self, title: str) -> Optional[Dict]:
        """Get first job matching exact title"""
        query = f"SELECT * FROM {self.TABLE_NAME} WHERE {DBFields.TITLE} = %s LIMIT 1;"
        try:
            self.cursor.execute(query, (title,))
            return self.cursor.fetchone()
        except psycopg2.Error as e:
            logger.error(f"Error fetching job by title: {e}")
            raise

    # READ - Multiple Entries
    def get_all_jobs(self, limit: Optional[int] = None) -> List[Dict]:
        """Get all jobs, optionally limited"""
        query = f"SELECT * FROM {self.TABLE_NAME} ORDER BY {DBFields.CREATED_AT} DESC"
        if limit:
            query += f" LIMIT {limit};"
        try:
            self.cursor.execute(query)
            return self.cursor.fetchall()
        except psycopg2.Error as e:
            logger.error(f"Error fetching all jobs: {e}")
            raise

    def get_jobs_by_company(self, company: str) -> List[Dict]:
        """Get all jobs from a specific company"""
        query = f"SELECT * FROM {self.TABLE_NAME} WHERE {DBFields.COMPANY} = %s ORDER BY {DBFields.CREATED_AT} DESC;"
        try:
            self.cursor.execute(query, (company,))
            return self.cursor.fetchall()
        except psycopg2.Error as e:
            logger.error(f"Error fetching jobs by company: {e}")
            raise

    def get_jobs_by_source(self, source: str) -> List[Dict]:
        """Get all jobs from a specific source"""
        query = f"SELECT * FROM {self.TABLE_NAME} WHERE {DBFields.SOURCE} = %s ORDER BY {DBFields.CREATED_AT} DESC;"
        try:
            self.cursor.execute(query, (source,))
            return self.cursor.fetchall()
        except psycopg2.Error as e:
            logger.error(f"Error fetching jobs by source: {e}")
            raise

    def get_remote_jobs(self) -> List[Dict]:
        """Get all remote jobs"""
        query = f"SELECT * FROM {self.TABLE_NAME} WHERE {DBFields.REMOTE} = TRUE ORDER BY {DBFields.CREATED_AT} DESC;"
        try:
            self.cursor.execute(query)
            return self.cursor.fetchall()
        except psycopg2.Error as e:
            logger.error(f"Error fetching remote jobs: {e}")
            raise

    def search_jobs(self, keyword: str) -> List[Dict]:
        """Search jobs by keyword in all relevant fields"""
        query = f"""
            SELECT * FROM {self.TABLE_NAME}
            WHERE {DBFields.TITLE} ILIKE %s
            OR {DBFields.COMPANY} ILIKE %s
            OR {DBFields.LOCATION} ILIKE %s
            OR {DBFields.SPONSORSHIP} ILIKE %s
            OR {DBFields.DESCRIPTION} ILIKE %s
            ORDER BY {DBFields.CREATED_AT} DESC;
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

    def get_jobs_with_sponsorship(
        self, 
        sponsorship: str = None
    ) -> List[Dict]:
        """Get jobs filtered by sponsorship status"""
        if sponsorship is None:
            sponsorship = SponsorshipStatus.LIKELY.value
            
        try:
            if sponsorship:
                query = f"SELECT * FROM {self.TABLE_NAME} WHERE {DBFields.SPONSORSHIP} = %s ORDER BY {DBFields.CREATED_AT} DESC;"
                self.cursor.execute(query, (sponsorship,))
            else:
                query = f"SELECT * FROM {self.TABLE_NAME} WHERE {DBFields.SPONSORSHIP} IS NOT NULL ORDER BY {DBFields.CREATED_AT} DESC;"
                self.cursor.execute(query)
            return self.cursor.fetchall()
        except psycopg2.Error as e:
            logger.error(f"Error fetching jobs with sponsorship: {e}")
            raise

    def get_jobs_filtered(
        self, 
        source: Optional[str] = None, 
        remote: Optional[bool] = None, 
        sponsorship: Optional[str] = None, 
        limit: Optional[int] = None
    ) -> List[Dict]:
        """Get jobs with flexible filtering options"""
        query = f"SELECT * FROM {self.TABLE_NAME} WHERE 1=1"
        params = []
        
        if source:
            query += f" AND {DBFields.SOURCE} = %s"
            params.append(source)
        
        if remote is not None:
            query += f" AND {DBFields.REMOTE} = %s"
            params.append(remote)
        
        if sponsorship:
            query += f" AND {DBFields.SPONSORSHIP} = %s"
            params.append(sponsorship)
        
        query += f" ORDER BY {DBFields.CREATED_AT} DESC"
        
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
        """Update job fields. Pass fields as keyword arguments"""
        allowed_fields = DBFields.updatable_fields()
        updates = {k: v for k, v in kwargs.items() if k in allowed_fields}

        if not updates:
            logger.warning("No valid fields provided for update")
            return False

        set_clause = ", ".join([f"{field} = %s" for field in updates.keys()])
        query = f"UPDATE {self.TABLE_NAME} SET {set_clause} WHERE {DBFields.ID} = %s;"

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
        """Delete a job by ID"""
        query = f"DELETE FROM {self.TABLE_NAME} WHERE {DBFields.ID} = %s;"
        try:
            self.cursor.execute(query, (job_id,))
            self.conn.commit()
            return self.cursor.rowcount > 0
        except psycopg2.Error as e:
            self.conn.rollback()
            logger.error(f"Error deleting job: {e}")
            raise

    def delete_jobs_by_company(self, company: str) -> int:
        """Delete all jobs from a company. Returns number of deleted rows"""
        query = f"DELETE FROM {self.TABLE_NAME} WHERE {DBFields.COMPANY} = %s;"
        try:
            self.cursor.execute(query, (company,))
            self.conn.commit()
            return self.cursor.rowcount
        except psycopg2.Error as e:
            self.conn.rollback()
            logger.error(f"Error deleting jobs by company: {e}")
            raise

    def delete_jobs_by_source(self, source: str) -> int:
        """Delete all jobs from a specific source"""
        query = f"DELETE FROM {self.TABLE_NAME} WHERE {DBFields.SOURCE} = %s;"
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
        """Delete all jobs"""
        query = f"DELETE FROM {self.TABLE_NAME};"
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
        """Get total number of jobs"""
        query = f"SELECT COUNT(*) as count FROM {self.TABLE_NAME};"
        try:
            self.cursor.execute(query)
            return self.cursor.fetchone()['count']
        except psycopg2.Error as e:
            logger.error(f"Error counting jobs: {e}")
            raise

    def count_jobs_by_company(self, company: str) -> int:
        """Get number of jobs for a specific company"""
        query = f"SELECT COUNT(*) as count FROM {self.TABLE_NAME} WHERE {DBFields.COMPANY} = %s;"
        try:
            self.cursor.execute(query, (company,))
            return self.cursor.fetchone()['count']
        except psycopg2.Error as e:
            logger.error(f"Error counting jobs by company: {e}")
            raise

    def get_statistics(self) -> Dict[str, Any]:
        """Get comprehensive statistics about jobs in database"""
        stats_query = f"""
            SELECT 
                COUNT(*) as total_jobs,
                COUNT(*) FILTER (WHERE {DBFields.SPONSORSHIP} = %s) as with_sponsorship,
                COUNT(*) FILTER (WHERE {DBFields.REMOTE} = TRUE) as remote_jobs,
                COUNT(*) FILTER (WHERE {DBFields.SOURCE} = %s) as from_simplify,
                COUNT(*) FILTER (WHERE {DBFields.SOURCE} = %s) as from_jsearch,
                COUNT(*) FILTER (WHERE {DBFields.SOURCE} = %s) as from_remoteok,
                COUNT(DISTINCT {DBFields.COMPANY}) as unique_companies
            FROM {self.TABLE_NAME};
        """
        try:
            self.cursor.execute(stats_query, (
                SponsorshipStatus.LIKELY.value,
                JobSource.SIMPLIFY.value,
                JobSource.JSEARCH.value,
                JobSource.REMOTEOK.value
            ))
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