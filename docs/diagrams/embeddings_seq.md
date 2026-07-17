```mermaid
%% sequenceDiagram — run_embedding_pass() batch loop
sequenceDiagram
    participant Dev as Manual run (python -m Tasks.embeddings)
    participant Run as run_embedding_pass
    participant DB as JobDatabase
    participant Ollama as Ollama /api/embeddings
    participant Bar as tqdm progress bar
    participant Discord as notify_discord

    Dev->>Run: run_embedding_pass(batch_size=50)
    Run->>DB: select(job_list, filters={enriched: True}, raw_where="enrich_attempts < 5", limit=50)
    DB-->>Run: rows

    alt no rows
        Run-->>Dev: stats (nothing pending)
    else rows to process
        Run->>Bar: open tqdm(total=len(rows)); start 1s background refresh thread

        loop each row
            Run->>Run: _build_embedding_text(job) — title + description + tags(skills/technologies/requirements)
            Run->>Ollama: POST /api/embeddings {model: nomic-embed-text, prompt: text}
            Ollama-->>Run: embedding vector
            Run->>DB: update(job_list, {embedding: Vector(embedding)}, filters={id})
            Run->>Run: maybe_promote_to_example_bank(job, db, embedding)

            alt enrich_attempts > 1
                Run-->>Run: skip — too many failed enrich attempts
            else fails passes_sanity_checks (role_type/pay_range/location/description length)
                Run-->>Run: skip — sanity check failed
            else too_similar_to_existing_example (cosine sim >= 0.95)
                Run-->>Run: skip — near-duplicate of an existing example
            else
                Run->>DB: upsert(enrichment_examples, {source_job_id, raw_description,\nextracted_json, embedding, verified_by: "auto_clean_pass"},\nconflict_column=[source_job_id])
                Run->>Run: stats.promoted += 1
            end

            Run->>Bar: update(1), set_postfix(promoted/embedded/errors/enrich_attempts)
        end

        Run->>Discord: notify_discord("Embedding pass complete — embedded: X, promoted: Y, errors: Z", file_path="embedded_jobs.txt")
        Run-->>Dev: stats {attempted, embedded, promoted, errors}
    end
```
