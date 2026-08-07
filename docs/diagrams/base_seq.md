```mermaid
%% flowchart — _upsert_company flow
flowchart TD
    A["JobSourceBase subclass calls _upsert_company(name, company_url)"] --> B{self._db is None?}
    B -->|yes| C["JobDatabase.create() → self._db = db instance"]
    B -->|no| D["upsert(table='company', data={name: name.lower(), company_url?}, conflict_column='name')"]
    C --> D
    D --> E{"upsert returns empty dict?<br/>(conflict, no RETURNING row)"}
    E -->|yes| F["selectOne(table='company', filters={name: name.lower()}) → company dict"]
    E -->|no, row returned| G[company dict from upsert]
    F --> H[return company dict]
    G --> H
```

```mermaid
%% flowchart — _map_jobs pipeline (iterate, map, filter None)
flowchart TD
    A["Caller (fetch_jobs) calls await _map_jobs(raw_jobs List[Dict])"] --> B["skip any None entries in input list"]
    B --> C[loop for each non-None job in raw_jobs]
    C --> D["await _map_job(job)<br/>(subclass must override — base raises NotImplementedError)"]
    D --> E[collect result: Job or None]
    E --> F{more jobs in raw_jobs?}
    F -->|yes| C
    F -->|no| G[filter out None results]
    G --> H[return List[Job] to Caller]
```
