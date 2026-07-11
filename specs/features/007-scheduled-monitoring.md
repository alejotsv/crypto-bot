# Feature: Scheduled monitoring (cron / Raspberry Pi)

Status: Done
Depends on: [006-stop-loss-take-profit](006-stop-loss-take-profit.md)
Related ADRs: None

## Summary

`crypto_bot`'s reconciliation check (feature 6) only runs when someone
invokes it — there's no background process. This feature makes that
happen on a schedule automatically, on a machine that's on 24/7, using
plain **cron** to re-run the check every 2 minutes. No new always-on
process or daemon is introduced — cron just invokes a script repeatedly,
consistent with the same choice already made in the OANDA sibling
project (`trading-bot`).

**Confirmed with the user (2026-07-10):** this runs on the same
Raspberry Pi already running the OANDA sibling project's cron job. This
is fine — each project is a separate repo, separate `.env`/credentials,
separate log file, separate crontab line; short-lived scripts with no
shared state, so there's no resource contention or interference between
the two.

## Goals

- A documented crontab entry that runs the reconciliation check on a
  fixed 2-minute interval.
- Output from each run captured to a log file.
- Clear README steps to get this running unattended on the Pi, following
  the same pattern already documented for the OANDA sibling project.

## Non-Goals

- No always-on daemon, systemd service, Docker container, or process
  supervisor — cron + a log file redirect is enough for this project's
  scope.
- No automated deployment/CI pipeline to the Pi — copying files over is
  a manual step, documented but not automated.
- No change to feature 6's reconciliation logic itself — this feature
  only schedules it.
- No consolidated multi-check entrypoint yet (the OANDA project's
  `run_cycle.py` combines several checks into one cron line) — this
  project only has one thing to schedule so far (the reconciliation
  check); revisit once there's more than one.

## Requirements

1. A documented crontab line:
   ```
   */2 * * * * cd /home/pi/crypto-bot && .venv/bin/python -m crypto_bot.run_cycle >> logs/reconcile.log 2>&1
   ```
   `crypto_bot/run_cycle.py` (new module) wraps `check_and_reconcile_exits`
   with settings/client construction and logs each action taken (or "no
   action needed").
2. A `logs/` directory (gitignored) that the cron job appends to.
3. README section "Running continuously on a Raspberry Pi" covering:
   - Copying the repo to the Pi and creating a real `.env` there (never
     committed, never copied through git).
   - Creating the venv and installing `requirements.txt` on the Pi.
   - Adding the crontab entry (`crontab -e`) alongside the OANDA sibling
     project's existing one, if both run on the same Pi.
   - Where to find logs and how to confirm it's actually running.
4. Check interval is configurable only via the crontab schedule itself
   (no new env var).

## Design / Approach

`crypto_bot/run_cycle.py` is the one small piece of new code: builds
settings/clients, calls `check_and_reconcile_exits`, and logs the
result. Everything else is deployment/ops — the crontab entry plus the
`logs/` convention above.

## Environment Variables / Config

None new. The Pi needs its own `.env` with real credentials — not
committed, copied over manually or re-created directly on the Pi.

## Acceptance Criteria

- [x] Crontab entry documented, running every 2 minutes.
- [x] `logs/` (and `exit_state.json`) added to `.gitignore`.
- [x] README section added with setup steps.
- [x] `crypto_bot/run_cycle.py` implemented and unit-tested (2/2 tests:
      logs "no action needed" when nothing happens, logs each action's
      symbol/type/detail otherwise); verified live against the real
      paper account (`python -m crypto_bot.run_cycle` ran cleanly).
- [ ] Deployed and verified on the actual Raspberry Pi (the same one
      running the OANDA sibling project): crontab entry runs on
      schedule, the log file grows over time, and its content never
      contains the API key/secret. **Not yet done — requires the user's
      manual deployment step**, same as every other "deploy to the Pi"
      criterion in this project.

## Open Questions

None. Interval (2 minutes) and shared-Pi placement both confirmed with
the user 2026-07-10 — see feature 6's Open Questions for the full
reasoning (crypto's higher volatility justifies a tighter interval than
the OANDA project's 5 minutes; the check itself is cheap enough that
this isn't a rate-limit or resource concern).

## Out of Scope / Future Work

- A consolidated multi-check entrypoint, if/when this project grows a
  second thing to schedule (e.g. an automated entry signal, if ever
  built) — expected to be a one-line crontab edit at that point, not a
  new scheduling mechanism, same precedent as the OANDA project.
- Alerting when the cron job itself fails silently.
