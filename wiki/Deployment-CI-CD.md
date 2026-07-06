# Deployment & CI/CD

Three GitHub Actions workflows, all deploying via SSH to a DigitalOcean droplet at `/var/www/libra/`, running under a `libra` virtualenv and a `libra` systemd service.

## `deploy.yaml` — API deploy

Trigger: push to `master`. Pulls latest code (`git reset --hard origin/master`), reinstalls requirements, `sudo systemctl restart libra`. Discord notification on success/failure via webhook + role mention.

## `scarpe.yaml` — scrape + enrich cron

```
0 5 * * *   → 12 AM EST
0 10 * * *  → 5 AM EST
0 15 * * *  → 10 AM EST
0 20 * * *  → 3 PM EST
0 1 * * *   → 8 PM EST
```

(also `workflow_dispatch` for manual runs)

- **`scrape` job**: runs on every scheduled trigger — SSHes in, pulls latest, runs `Tasks/scrape.py`, logs to `logs/scrape.log`
- **`enrich` job**: `needs: scrape`, but only actually runs when the trigger is the `0 5 * * *` cron slot or a manual `workflow_dispatch` — i.e. enrichment runs once a day, not on every scrape cycle, to bound Groq usage

Both jobs post a Discord failure notification if the SSH step fails; success isn't announced for these (only for `deploy.yaml`).

## `notify.yaml` — general repo activity

Separate from deploy/scrape — fires on push to **any** branch and on issue open/reopen/close. Posts to Discord with commit info (repo, branch, SHA, message, author) or issue info (title, opener, link). This is the one that pings on every push regardless of whether it's `master`.

## Typo note

The scrape workflow file is named `scarpe.yaml` (transposed letters) — harmless since GitHub Actions doesn't care about filenames, but worth knowing if you're hunting for it.

## Secrets required

`SSH_HOST`, `SSH_USER`, `SSH_PRIVATE_KEY`, `DISCORD_WEBHOOK`, `DISCORD_ROLE_ID` (only used in `notify.yaml`).
