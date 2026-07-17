from uuid import UUID

from Utils.constants import Config
import ssl, asyncpg, json
import uuid
import datetime
from pgvector.asyncpg import register_vector
from pgvector import Vector


class JobDatabase:
    "Asynchronous database connection and operations using asyncpg."

    FETCH = "fetch"
    FETCHVAL = "fetchval"
    FETCHROW = "fetchrow"
    _instance = None
    _pool: asyncpg.Pool

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    @classmethod
    async def create(cls) -> "JobDatabase":
        if cls._instance is not None:
            return cls._instance

        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        
        async def init_connection(conn):
            await register_vector(conn) #type: ignore

        cls._pool = await asyncpg.create_pool(
            host=Config.DB_HOST,
            port=Config.DB_PORT,
            database=Config.DB_NAME,    
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            ssl=ssl_ctx,
            min_size=2,
            max_size=10,
            init=init_connection,
        )

        cls._instance = cls(cls._pool)
        return cls._instance


    # ----------------------------------------------------
    #  CRUD
    # ----------------------------------------------------
    async def select(
        self,
        table: str,
        columns: list = [],
        filters: dict = {},
        raw_where: str = '',
        raw_params: list = [],
        order_by: str = "created_at DESC",
        limit: int = 100,
    )->list[dict]:
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
                sql += f" AND ({raw_where})" if filters else f" WHERE {raw_where}"
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

    async def selectOne(
        self,
        table: str,
        columns: list = [],
        filters: dict = {},
        order_by: str = "created_at DESC",
    ) -> dict:
        try:
            row = await self.select(table, columns=columns, filters=filters, order_by=order_by, limit=1)
            return row[0] if row else {}
        except Exception as e:
            Config.logger.error(f"Error during selectOne from {table}: {e}")
            raise

    async def get_or_create_company(self, name: str) -> UUID:
        """Get the company ID for a given name, creating a new entry if it doesn't exist. Created for test   mOde in azalea."""
        row = await self.selectOne(
            "company",
            columns=["id"],
            filters={"lower(name)": name.lower()}
        )
        if row:
            return row["id"]
        row = await self.upsert(
            "company",
            data={"name": name},
            conflict_column="name"
        )
        return row["id"]
    # -------------------------
    # UPSERT
    # -------------------------
    def _serialize(self, v):
        if isinstance(v, Vector):
            return v       
        if isinstance(v, (dict, list)):
            return json.dumps(v, default=self._json_default)
        return v
    
    def _json_default(self,o):
        if isinstance(o, uuid.UUID):
            return str(o)
        if isinstance(o, (datetime.datetime, datetime.date)):
            return o.isoformat()
       
        raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")

  
    async def upsert(self, table: str, data: dict, conflict_column: str | list | None = None)-> dict:
        try:
            columns = list(data.keys())
            
            values = [self._serialize(v) for v in data.values()]
            placeholders = ", ".join(f"${i+1}" for i in range(len(values)))
            cols = ", ".join(columns)

            _, on_conflict = self._build_conflict_clause(columns, conflict_column, table)

            sql = f"""
                INSERT INTO {table} ({cols})
                VALUES ({placeholders})
                {on_conflict}
                RETURNING *;
            """
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(sql, *values)
                return dict(row) if row else {}
        except Exception as e:
            Config.logger.error(f"Error during upsert to {table}: {e}")
            raise

    async def bulk_upsert(self, table: str, rows: list[dict], conflict_column: str | list | None = None)-> list[dict]:
        try:
            if not rows:
                return []

            columns = list(rows[0].keys())
            cols = ", ".join(columns)

            _, on_conflict = self._build_conflict_clause(columns, conflict_column, table)

            values = []
            placeholder_groups = []
            param_index = 1

            for row in rows:
                group = []
                for col in columns:
                    val = row[col]
                    values.append(self._serialize(val))
                    group.append(f"${param_index}")
                    param_index += 1
                placeholder_groups.append(f"({', '.join(group)})")

            placeholders = ", ".join(placeholder_groups)

            sql = f"""
                INSERT INTO {table} ({cols})
                VALUES {placeholders}
                {on_conflict}
                RETURNING *;
            """
            async with self.pool.acquire() as conn:
                result = await conn.fetch(sql, *values)
                return [dict(r) for r in result]
        except Exception as e:
            Config.logger.error(f"Error during bulk_upsert to {table}: {e}")
            raise

    async def update(self, table: str, data: dict, filters: dict) -> dict:
        try:
            set_clause = ", ".join(f"{k} = ${i+1}" for i, k in enumerate(data.keys()))
            where_clause = " AND ".join(f"{k} = ${len(data)+i+1}" for i, k in enumerate(filters.keys()))
            sql = f"UPDATE {table} SET {set_clause} WHERE {where_clause} RETURNING *;"
            all_params = list(data.values()) + list(filters.values())
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(sql, *all_params)
                return dict(row) if row else {}
        except Exception as e:
            Config.logger.error(f"Error during update to {table}: {e}")
            raise

    async def delete(self, table: str, filters: dict)-> list[dict]:
        try:
            where_clause = " AND ".join(
                f"{k} = ${i+1}" for i, k in enumerate(filters.keys())
            )
            sql = f"DELETE FROM {table} WHERE {where_clause} RETURNING *;"
            async with self.pool.acquire() as conn:
                return await conn.fetch(sql, *list(filters.values()))
        except Exception as e:
            Config.logger.error(f"Error during delete from {table}: {e}")
            raise

    async def call_function(self, fn: str, params=None, fetch_type=None):
        try:
            params = params or []
            fetch_type = fetch_type or self.FETCH
            placeholders = ", ".join(f"${i+1}" for i in range(len(params)))
            sql = f"SELECT * FROM {fn}({placeholders});"
            async with self.pool.acquire() as conn:
                if fetch_type == self.FETCHVAL:
                    return await conn.fetchval(sql, *params)
                elif fetch_type == self.FETCHROW:
                    return await conn.fetchrow(sql, *params)
                else:
                    return await conn.fetch(sql, *params)
        except Exception as e:
            Config.logger.error(f"Error during call_function {fn}: {e}")
            raise

    # ----------------------------------------------------
    #  RAW QUERY
    # ----------------------------------------------------
    async def raw(self, sql: str, params: list = []) -> list[dict]:
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(sql, *params)
                return [dict(r) for r in rows]
        except Exception as e:
            Config.logger.error(f"Error during raw query: {e}")
            raise

    # ----------------------------------------------------
    #  CONFLICT CLAUSE BUILDER
    # ----------------------------------------------------
    def _build_conflict_clause(
        self,
        columns: list[str],
        conflict_column: str | list | None,
        table_name: str,          # required — used to qualify existing row reference
    ) -> tuple[list[str], str]:
        """
        Build the ON CONFLICT ... DO UPDATE clause.

        Uses COALESCE so existing non-null values are never overwritten by a null
        from a re-scrape.  e.g.:
            title = COALESCE(EXCLUDED.title, job_list.title)

        conflict_column can be:
          - None                  → ON CONFLICT DO NOTHING
          - "identifier"          → ON CONFLICT (identifier) DO UPDATE ...
          - ["company", "title"]  → ON CONFLICT (company, title) DO UPDATE ...
        """
        if not conflict_column:
            return [], "ON CONFLICT DO NOTHING"

        conflict_cols = conflict_column if isinstance(conflict_column, list) else [conflict_column]
        conflict_target = ", ".join(conflict_cols)

        update_fields = [c for c in columns if c not in conflict_cols]
        if not update_fields:
            return conflict_cols, f"ON CONFLICT ({conflict_target}) DO NOTHING"

        update_clause = ", ".join(
            f"{c} = COALESCE(EXCLUDED.{c}, {table_name}.{c})"
            for c in update_fields
        )
        return conflict_cols, f"ON CONFLICT ({conflict_target}) DO UPDATE SET {update_clause}"