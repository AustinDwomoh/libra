# Deployment & CI/CD

Five GitHub Actions workflows, most deploying via SSH to a DigitalOcean droplet at `/var/www/libra/`, running under a `libra` virtualenv and a `libra` systemd service.

## `deploy.yaml` — API deploy

Trigger: push to `master`. Pulls latest code (`git reset --hard origin/master`), reinstalls requirements, `sudo systemctl restart libra`. Discord notification on success/failure via webhook + role mention.

## `Automations.yaml` — scrape + enrich + expire cron

This replaces the old single scrape/enrich workflow (previously named `scarpe.yaml`, since renamed and restructured into three jobs). Schedule:

```
0 5 * * *   → 12 AM EST
0 10 * * *  → 5 AM EST
0 15 * * *  → 10 AM EST
0 20 * * *  → 3 PM EST
0 1 * * *   → 8 PM EST
```

(also `workflow_dispatch` for manual runs)

- **`scrape` job**: runs on every scheduled trigger — SSHes in, `git reset --hard origin/master`, reinstalls requirements, runs `Tasks/scrape.py`, logs to `logs/scrape.log`. Notifies Discord on failure only.
- **`enrich` job**: `needs: scrape`, but only actually runs when the trigger is the `0 5 * * *` cron slot or a manual `workflow_dispatch` — i.e. enrichment runs once a day, not on every scrape cycle. Runs `Tasks/enrich.py`, logs to `logs/enrich.log`. Notifies Discord on failure only.
- **`expired` job**: gated on `github.event.schedule == '0 6 * * 6'` (Saturday 6 AM UTC) or manual dispatch — **note this cron expression isn't actually one of the five listed under `on.schedule` above**, so as written this job's `if` condition can only ever be satisfied by a manual `workflow_dispatch`, never by the schedule itself (see [[Roadmap]]). Runs `Tasks/expired.py`, logs to `logs/expired.log`, and notifies Discord on **both** success and failure (unlike the other two jobs), attaching the log file to the message.

`Tasks/embeddings.py` (the new standalone embedding/RAG pass) has **no job in this workflow at all** — it isn't scheduled anywhere yet. It must be run manually on the droplet until a job is added.

## `PR checklist.yaml`

Runs a concurrency-controlled checklist check on pull requests (see the repo's `.github/PULL_REQUEST_TEMPLATE.md` for what the checklist itself covers). Not tied to deploy/scrape — purely a PR gate.

## `wiki-sync.yaml`

Syncs the `wiki/` folder in this repo to the GitHub Wiki on push, so the pages here (this one included) stay mirrored without a manual publish step. This is the workflow whose output you're reading if you're viewing this on the GitHub Wiki rather than in-repo.

## `notify.yaml` — general repo activity

Separate from deploy/scrape — fires on push to **any** branch and on issue open/reopen/close. Posts to Discord with commit info (repo, branch, SHA, message, author) or issue info (title, opener, link). This is the one that pings on every push regardless of whether it's `master`.

## Secrets required

`SSH_HOST`, `SSH_USER`, `SSH_PRIVATE_KEY`, `DISCORD_WEBHOOK`, `DISCORD_ROLE_ID` (only used in `notify.yaml`).