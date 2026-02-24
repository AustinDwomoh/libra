
from services.config import Config
import ssl, asyncpg, json

class JobDatabase:
    "Make asynchronous database connection and operations using psycopg2 use rimuru as template"
    FETCH = "fetch"
    FETCHVAL = "fetchval"
    FETCHROW = "fetchrow"
    _instance = None          
    _pool: asyncpg.Pool = None 
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    # ----------------------------------------------------
    # FACTORY: Create async Rimiru instance
    # ----------------------------------------------------
    @classmethod
    async def create(cls):
        """
        The `create` function is an asynchronous method that creates a connection pool to a PostgreSQL
        database with specified configurations.
        
        :param cls: The `cls` parameter in the `create` method is a reference to the class itself. In this
        context, it is used to access class attributes and methods
        :return: The `create` method is returning an instance of the class `cls`. If `cls._instance` is
        not None, it returns the existing instance stored in `cls._instance`. Otherwise, it creates a new
        instance of the class using the asyncpg connection pool created with the specified configurations
        and returns this new instance.
        """
        if cls._instance is not None:
            return cls._instance

        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        cls._pool = await asyncpg.create_pool(
            host=Config.DB_HOST,
            port=Config.DB_PORT,
            database=Config.DB_NAME,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            ssl=ssl_ctx,
            min_size=2,
            max_size=10,
        )

        cls._instance = cls(cls._pool)
        return cls._instance


    # ----------------------------------------------------
    #  CRUD
    # ----------------------------------------------------
    async def select(self, table: str, columns: list = None, filters: dict = None, 
                raw_where: str = None, raw_params: list = None,
                order_by: str = None, limit: int = None):
        """
        Select records with optional filtering
        
        :param table: Table name
        :param columns: List of columns to select (default: all)
        :param filters: Dictionary of column=value filters
        :param raw_where: Raw WHERE clause (use with raw_params for safety)
        :param raw_params: Parameters for raw_where clause
        :param order_by: Column to order by
        :param limit: Maximum number of records to return
        """
        try:
            cols = ", ".join(columns) if columns else "*"
            sql = f"SELECT {cols} FROM {table}"
            params = []
            param_count = 1

            if filters:
                where_clauses = []
                for key, value in filters.items():
                    where_clauses.append(f"{key} = ${param_count}")
                    params.append(value)
                    param_count += 1
                sql += f" WHERE {' AND '.join(where_clauses)}"

            if raw_where:
                if filters:
                    sql += f" AND ({raw_where})"
                else:
                    sql += f" WHERE {raw_where}"
                if raw_params:
                    params.extend(raw_params)

            if order_by:
                sql += f" ORDER BY {order_by}"

            if limit:
                sql += f" LIMIT {limit}"

            sql += ";"

            async with self.pool.acquire() as conn:
                rows = await conn.fetch(sql, *params)
                return [dict(r) for r in rows]
        except Exception as e:
            Config.logger.error(f"Error during select from {table}: {e}")
            raise

    async def selectOne(self, table: str, columns: list = None, filters: dict = None, order_by: str = None):
        """
        Select a single record with optional filtering
        
        :param table: Table name
        :param columns: List of columns to select (default: all)
        :param filters: Dictionary of column=value filters
        :param order_by: Column to order by (e.g., "created_at DESC")
        """
        try:
            row = await self.select(table, columns, filters, order_by, limit=1)
            return row[0] if row else None
        except Exception as e:
            Config.logger.error(f"Error during selectOne from {table}: {e}")
            raise
   
    # -------------------------
    # UPSERT (INSERT or UPDATE)
    # -------------------------
    async def upsert(self, table: str, data: dict, conflict_column: str ):
        """Insert or update a record based on conflict column
            To use this method, provide the following
            its important you know the unique constraint of the table you are upserting to.  The conflict_column parameter should be set to that unique constraint column.
            
                parameters:
                    :param table: Table name
                    :param data: Dictionary of column-value pairs
                    :param conflict_column: Column name to check for conflicts
            """
        try:
            columns = list(data.keys())
            values = [
                json.dumps(v) if isinstance(v, (dict, list)) else v
                for v in data.values()
            ]

            placeholders = ", ".join(f"${i+1}" for i in range(len(values)))
            cols = ", ".join(columns)
            update_cols = ", ".join(f"{k} = EXCLUDED.{k}" for k in columns if k != conflict_column)

            sql = f"""
                INSERT INTO {table} ({cols}) 
                VALUES ({placeholders})
                ON CONFLICT ({conflict_column}) 
                DO UPDATE SET {update_cols}
                RETURNING *;
            """

            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(sql, *values) 
                return dict(row) if row else None
        except Exception as e:
            Config.logger.error(f"Error during upsert to {table}: {e}")
            raise
        # -------------------------
        # DELETE
    
    # -------------------------
    async def delete(self, table: str, filters: dict):
        """Delete records matching filters"""
        try:
            where_clause = " AND ".join(f"{k} = ${i+1}" for i, k in enumerate(filters.keys()))
            sql = f"DELETE FROM {table} WHERE {where_clause} RETURNING *;"
            params = list(filters.values())
    
            async with self.pool.acquire() as conn:
                return await conn.fetch(sql, *params)
        except Exception as e:
            Config.logger.error(f"Error during delete from {table}: {e}")
            raise
        
    # ----------------------------------------------------
    # ASYNC FUNCTION CALLS
    # ----------------------------------------------------
    async def call_function(self, fn: str, params=None, fetch_type=None):
        """
        fetch_type can be:
        - FetchType.FETCH: returns list of Record objects
        - FetchType.FETCHVAL: returns single scalar value
        - FetchType.FETCHROW: returns single Record object
        """
        try:
            params = params or []
            fetch_type = fetch_type or self.FETCH  # Default to FETCH
            
            placeholders = ", ".join(f"${i+1}" for i in range(len(params)))
            sql = f"SELECT * FROM {fn}({placeholders});"
    
            async with self.pool.acquire() as conn:
                if fetch_type == self.FETCHVAL:
                    return await conn.fetchval(sql, *params)
                elif fetch_type == self.FETCHROW:
                    return await conn.fetchrow(sql, *params)
                else:  # self.FETCH
                    return await conn.fetch(sql, *params)
        except Exception as e:
            Config.logger.error(f"Error during call_function {fn}: {e}")
            raise
