```mermaid
%% classDiagram — JobDatabase structure and relationships
classDiagram
    class JobDatabase {
        <<singleton>>
        +FETCH: str = "fetch"
        +FETCHVAL: str = "fetchval"
        +FETCHROW: str = "fetchrow"
        -_instance: JobDatabase
        -_pool: asyncpg.Pool
        +pool: asyncpg.Pool
        +create() JobDatabase$
        +select(table, columns, filters, raw_where, raw_params, order_by, limit) list[dict]
        +selectOne(table, columns, filters, order_by) dict
        +get_or_create_company(name) UUID
        +upsert(table, data, conflict_column) dict
        +bulk_upsert(table, rows, conflict_column) list[dict]
        +update(table, data, filters) dict
        +delete(table, filters) list[dict]
        +call_function(fn, params, fetch_type) any
        +raw(sql, params) list[dict]
        -_build_conflict_clause(columns, conflict_column, table_name) tuple
        -_serialize(v) any
        -_json_default(o) str
    }

    class asyncpg_Pool {
        <<external: asyncpg>>
        +acquire() Connection
        +create_pool(...) Pool
    }

    class Vector {
        <<external: pgvector>>
    }

    class Config {
        +DB_HOST
        +DB_PORT
        +DB_NAME
        +DB_USER
        +DB_PASSWORD
        +logger
    }

    JobDatabase --> asyncpg_Pool : pool (connection pool)
    JobDatabase --> Config : reads DB credentials + logger
    JobDatabase --> Vector : _serialize() passes pgvector Vector values through untouched

    note for JobDatabase "_serialize(v) replaces the old inline\njson.dumps(v) check in upsert/bulk_upsert:\n- Vector → passed through as-is (asyncpg + pgvector\n  driver handles the wire format)\n- dict/list → json.dumps(v, default=_json_default)\n  (_json_default stringifies UUID and\n  datetime/date so embedding/tags/pay_range\n  payloads containing them don't raise\n  TypeError)\n- everything else → passed through unchanged\n\nget_or_create_company(name) is new — added for\nAzalea test mode, where a JSON-backed job may carry\na company name instead of a UUID. Looks up by\nlower(name), creates via upsert(conflict_column='name')\nif not found."
```