# Deployment & CI/CD

The environment side of deployment. For the full breakdown of every GitHub
Actions workflow — triggers, jobs, cron rationale, secrets — see [[Workflows]].

## The box

A DigitalOcean droplet (4 GB RAM, Linux). Everything lives at `/var/www/libra/`:

```
/var/www/libra/
├── libra/            # the virtualenv (source libra/bin/activate)
├── logs/             # scrape.log, enrich.log, expired.log, run.log
├── .env              # DB creds, API keys (not in git)
└── <repo checkout>   # kept exactly at origin/master by every deploy
```

- **venv:** `libra/` — activated with `source libra/bin/activate` in every SSH
  script.
- **service:** a `libra` systemd unit runs the FastAPI app (via uvicorn/gunicorn).
  Restarted with `sudo systemctl restart libra`. The SSH user is **root**, so
  `sudo` is a no-op and `playwright install-deps` / the Ollama install script
  work without extra privilege setup.
- **code:** every deploy does `git fetch origin && git reset --hard
  origin/master` — the checkout is disposable and always matches `master`
  exactly. Don't hand-edit files on the droplet; they'll be blown away on the
  next push.
- **Ollama:** runs locally on the droplet. Models: `qwen2.5:3b-instruct`
  (enrichment + expiry LLM checks) and `nomic-embed-text` (embeddings). Both are
  pulled/verified by the deploy script.

## Deploy = code pull + environment reassertion

`deploy.yaml` fires on every push to `master` and, in one SSH step, both pulls
the new code **and** re-asserts the whole runtime environment:

```bash
git reset --hard origin/master
pip install -r requirements.txt --upgrade-strategy only-if-needed

# setup block — merged in from installer.ps1 so a deploy needs no follow-up
pip install --upgrade gunicorn uvicorn asyncpg pgvector ollama
playwright install && playwright install-deps
command -v ollama >/dev/null 2>&1 || curl -fsSL https://ollama.com/install.sh | sh
ollama list | grep -q "qwen2.5:3b-instruct" || ollama pull qwen2.5:3b-instruct
ollama list | grep -q "nomic-embed-text"   || ollama pull nomic-embed-text

sudo systemctl restart libra
```

The setup block is idempotent (no-op when the box is already current) and runs
**before** the service restart, so a failed model pull fails the deploy while
the running service is untouched — not after it restarts into a broken state.

This is why there's no separate "run the installer on the server" step any more.
`installer.ps1` is now **local dev machine setup only**.

## Scheduled tasks

Run by `Automations.yaml` (see [[Workflows]] for the full job wiring and the
reasoning behind the times):

| Task | Cadence | Cron (UTC) |
|---|---|---|
| `scrape` → `enrich` | 3×/week | Mon 08:00, Wed 14:00, Fri 20:00 |
| `expired` (weekly expiry sweep) | 1×/week | Sat 06:00 |

`enrich` runs after **every** scrape (`needs: scrape`, no schedule filter).
`Tasks/embeddings.py` is **not scheduled** anywhere yet and must be run manually
on the droplet.

## Secrets

`SSH_HOST`, `SSH_USER`, `SSH_PRIVATE_KEY`, `DISCORD_WEBHOOK`, `DISCORD_ROLE_ID`
(only `notify.yaml`), `WIKI_DEPLOY_TOKEN` (only `wiki-sync.yaml`).
