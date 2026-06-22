```mermaid
%% sequenceDiagram — create() singleton + pool init
sequenceDiagram
    participant Caller as Any caller
    participant DB as JobDatabase

    Caller->>DB: await JobDatabase.create()

    alt _instance already exists
        DB-->>Caller: _instance (cached)
    else first call
        DB->>DB: ssl.create_default_context()
        Note over DB: check_hostname=False, CERT_NONE
        DB->>DB: asyncpg.create_pool(host, port, db, user, password, ssl, min=2, max=10)
        DB->>DB: _instance = JobDatabase(_pool)
        DB-->>Caller: _instance
    end

```

```mermaid
%% sequenceDiagram — _build_conflict_clause (ON CONFLICT strategy)
sequenceDiagram
    participant Op as upsert / bulk_upsert
    participant B as _build_conflict_clause

    Op->>B: _build_conflict_clause(columns, conflict_column, table_name)

    alt conflict_column is None
        B-->>Op: "ON CONFLICT DO NOTHING"
    else conflict_column is str or list
        B->>B: conflict_cols = [conflict_column] or conflict_column
        B->>B: update_fields = columns - conflict_cols
        alt no update_fields
            B-->>Op: "ON CONFLICT (cols) DO NOTHING"
        else fields to update
            B->>B: build COALESCE per field
            Note over B: col = COALESCE(EXCLUDED.col, table.col)
            Note over B: preserves existing non-null on re-scrape
            B-->>Op: "ON CONFLICT (cols) DO UPDATE SET ..."
        end
    end

```