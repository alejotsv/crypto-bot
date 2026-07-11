# Feature: Project structure and dependencies

Status: Done
Depends on: none
Related ADRs: [0001-spec-driven-development](../adr/0001-spec-driven-development.md), [0002-use-alpaca-py](../adr/0002-use-alpaca-py.md), [0003-paper-account-until-explicit-go-live](../adr/0003-paper-account-until-explicit-go-live.md)

## Summary

Establish the repository layout, dependency set, and configuration
conventions that every later feature (auth, price data, orders,
positions, stop-loss/take-profit) will build on. This spec defines
*structure only* — no trading logic.

## Goals

- A predictable package layout that separates concerns (config, Alpaca
  client, market data, orders, positions) so each later feature has an
  obvious home.
- A minimal, pinned dependency set — nothing speculative.
- A configuration convention (env vars via `.env`) that every later
  feature reuses, so credentials handling is defined once, not
  per-feature.
- Enough scaffolding (`tests/`, a place for a CLI entry point) to start
  writing and testing features 2–6 without restructuring later.

## Non-Goals

- No actual Alpaca client code, authentication logic, or trading logic —
  that's features 2+.
- No packaging/distribution concerns (no PyPI publishing, no Docker).
- No CI/CD setup.
- No logging framework beyond stdlib `logging` — keep it simple.
- No notification-channel config — not yet decided which channel (or
  whether one) this project will use.

## Requirements

1. **Directory layout** (see Design below) with an installable package
   under `crypto_bot/`, a `tests/` directory mirroring it, and this
   `specs/` tree.
2. **Dependency management** via a single `requirements.txt` (pinned,
   minimal versions) — no Poetry/PDM/etc.; this is a learning project and
   `pip install -r requirements.txt` should be all that's needed.
3. **Config loading convention**: a single `crypto_bot/config.py` module
   that loads environment variables at startup (via `python-dotenv` +
   `os.environ`). Only variables needed by features that exist *right
   now* are required (raise a clear error if missing). All later
   features read config through this module, not by calling
   `os.environ` directly elsewhere.
4. **Secrets stay out of git**: `.gitignore` excludes `.env`,
   `__pycache__`, `.venv`, etc. `.env.example` lists every variable name
   this feature's config needs, with placeholder (non-secret) values or
   blanks.
5. **Python version**: target Python 3.11+ (document in README).
6. **No trading logic, API calls, or network access in this feature** —
   it's pure scaffolding.

## Design / Approach

Proposed layout:

```
crypto-bot/
├── CLAUDE.md
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── specs/
│   ├── context/
│   ├── adr/
│   ├── features/
│   └── tasks/
├── crypto_bot/
│   ├── __init__.py
│   ├── config.py            # loads/validates env vars (this feature)
│   ├── alpaca_client.py     # Alpaca client wrapper           (feature 2)
│   ├── market_data.py       # price fetching                  (feature 3)
│   ├── orders.py            # order placement                 (feature 4)
│   ├── positions.py         # position monitoring              (feature 5)
│   └── exits.py             # stop-loss / take-profit          (feature 6)
├── main.py                  # CLI entry point (wired up incrementally)
└── tests/
    ├── __init__.py
    └── test_config.py
```

Module files for features 2–6 are created empty (or not at all) by this
feature — they're listed here to fix the intended shape of the package
so later specs don't need to re-litigate layout. Only `config.py` and
its test get real content in this feature.

### Dependencies (`requirements.txt`)

| Package | Purpose | Notes |
|---|---|---|
| `alpaca-py` | Alpaca's official Python SDK (trading + market data) | see ADR 0002 |
| `python-dotenv` | Load `.env` into environment variables | |
| `pytest` | Test runner | dev dependency, but kept in the same file for simplicity |

Versions to be pinned to latest stable at implementation time (recorded
in `requirements.txt` with `==`, not left floating).

### Configuration convention

`crypto_bot/config.py` exposes a `Settings` dataclass, built from the
environment once at import/startup. Using a dataclass (rather than bare
module constants) makes it easy to construct alternate `Settings`
instances in tests without monkeypatching environment variables.

- `ALPACA_API_KEY` — **required now** (feature 2 needs it next).
- `ALPACA_SECRET_KEY` — **required now**.
- `ALPACA_PAPER` (`true` | `false`) — defaults to `true` if unset (see
  ADR 0003); must be set explicitly to `false` for any live-account
  behavior. Parsed to a `bool` on the `Settings` dataclass.

Only `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` raise an error if missing.

## Environment Variables / Config

Defined in `.env.example` (placeholders only, never real values):

```
ALPACA_API_KEY=
ALPACA_SECRET_KEY=
ALPACA_PAPER=true
```

## Acceptance Criteria

- [x] Repository has the directory layout above (`main.py` omitted —
      nothing to wire up yet; created when a feature actually needs an
      entry point, not before).
- [x] `requirements.txt` exists with pinned versions of exactly the
      three dependencies listed (no extras added speculatively):
      `alpaca-py==0.43.5`, `python-dotenv==1.2.2`, `pytest==9.1.1`.
- [x] `.env.example` exists and lists all three variables with no real
      secrets.
- [x] `.gitignore` excludes `.env`, `__pycache__/`, `*.pyc`, `.venv/`.
- [x] `crypto_bot/config.py` loads env vars via `python-dotenv` into a
      `Settings` dataclass, defaults `ALPACA_PAPER` to `True`, and
      raises a clear error if `ALPACA_API_KEY` or `ALPACA_SECRET_KEY` is
      missing.
- [x] `tests/test_config.py` covers: required vars present → config
      loads; required var missing → clear error raised; `ALPACA_PAPER`
      unset → defaults to `True`; `ALPACA_PAPER=false` → parses to
      `False`. 5/5 passing.
- [x] `README.md` documents setup: clone, create venv, `pip install -r
      requirements.txt`, copy `.env.example` to `.env` and fill in
      values, how to run tests.
- [x] Running the test suite (`pytest`) passes with no network access
      required.

## Open Questions

None.

## Update (2026-07-10): required `ALPACA_BASE_URL`, cross-validated against `ALPACA_PAPER`

Added a fourth config variable: `ALPACA_BASE_URL`. `alpaca-py`'s
`TradingClient` already supports a `url_override` parameter separate
from the `paper` flag — this exposes it via config so a future Alpaca
endpoint change, or a need to point at a non-default host, only ever
requires editing `.env`, never code.

Initially added as optional (defaulting to `None`, letting the SDK
infer the host from `ALPACA_PAPER`), then changed to **required** — the
point is for it to act as a deliberate fail-safe, not a convenience
default. `load_settings()` now raises `ConfigError` if `ALPACA_BASE_URL`
is missing, *and* if it doesn't exactly match the host expected for the
current `ALPACA_PAPER` value (`PAPER_BASE_URL`/`LIVE_BASE_URL` module
constants) — e.g. `ALPACA_PAPER=true` with the live URL set fails to
load rather than silently trading against the wrong environment. Two
independently-set values having to agree is what makes this a real
check rather than one value quietly inferring the other.
`crypto_bot/config.py`'s `Settings` dataclass gained `alpaca_base_url:
str`. 8/8 tests passing.

## Out of Scope / Future Work

- Actual `alpaca_client.py`, `market_data.py`, `orders.py`,
  `positions.py`, `exits.py` implementations — features 2–6.
- Packaging for distribution, CI, containerization.
- Notification-channel config — decide when that feature is scoped.
