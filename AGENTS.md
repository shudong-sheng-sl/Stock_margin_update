# AGENTS.md — Maintainer & Agent Guide

Operational guide for anyone (human or AI agent) taking over this project. Read
this before making changes. It documents the non-obvious contracts and failure
modes that are easy to break.

> If you use Claude Code, you can `cp AGENTS.md CLAUDE.md` (or symlink) so it is
> auto-loaded; the content is vendor-neutral.

## What this project does

Tracks daily **margin trading (融资融券)** data for a personal A-share
watchlist and produces a report of the latest ~10 trading days. Two output
paths share the same data layer:

- **Email report** (`scripts/send_email_report.py`) — runs automatically via
  GitHub Actions and emails an HTML summary. This is the production path.
- **Spreadsheet export** (`scripts/export_report_xlsx.py`) — writes
  `daily_margin_report.xlsx` locally. Run manually. **Currently local-only:
  this script and its `openpyxl` dependency are NOT committed to the repo yet**
  (see Tech debt).

There is also a FastAPI dashboard (`app/main.py`, `app/api/routes.py`) exposing
`GET /api/margin-dashboard`, but the daily value comes from the email path.

## Architecture & data flow

```
tracked_stocks.json  ─┐
                       ├─►  get_margin_dashboard()  ──►  MarginDashboardResponse
akshare (exchanges) ──┘        (app/services/stocks.py)         │
                                                                ├─► send_email_report.py → HTML email
                                                                └─► export_report_xlsx.py → .xlsx
```

Everything funnels through `get_margin_dashboard()` in
`app/services/stocks.py`. The reports are pure renderers — they hold no stock
list and no fetching logic of their own. **To change what data is fetched, edit
`app/services/stocks.py` and/or `data/tracked_stocks.json`; to change how a
report looks, edit the relevant script.**

### Data sources (all via `akshare`)

- Margin detail: `ak.stock_margin_detail_sse(date=YYYYMMDD)` and
  `ak.stock_margin_detail_szse(date=YYYYMMDD)`.
- Prices: `ak.stock_zh_a_hist` (eastmoney, primary) with
  `ak.stock_zh_a_hist_tx` (tencent) as fallback.

Exchange column names the code depends on (these are akshare's, and can change
if akshare updates — a likely source of future breakage):

- SSE margin rows: `标的证券代码`, `融资余额`
- SZSE margin rows: `证券代码`, `融资余额`, `融券余额`, `融资融券余额`
- Price rows (eastmoney): `日期`, `收盘`, `涨跌幅`

`akshare` is a scraper over public exchange endpoints. It is pinned
(`akshare==1.16.86`) precisely because upgrades can silently change column names
or behavior. Treat any akshare version bump as a breaking-risk change and
re-verify parsing.

## The hard contract (read this before touching the fetch logic)

`_load_live_margin_dashboard()` walks backward from today and keeps only trading
days where **every** tracked stock has a margin-detail row. It requires
`TRADING_DAY_WINDOW` (10) such **complete** days within `MAX_LOOKBACK_DAYS`
(45), otherwise it raises `RuntimeError` and **no report is produced**.

Consequences:

- **Every stock in the watchlist must be margin-eligible (融资融券标的).** Adding
  a non-eligible stock means it never has a margin row, so zero days are ever
  "complete" → the whole report fails. This is the most common way to break the
  daily job. Verify eligibility before adding (search "<code> 融资融券余额" and
  confirm real balance data exists).
- A stock that gets suspended for a long stretch has the same effect.
- The pipeline is intentionally all-or-nothing (accuracy over partial data).
  There is currently no per-stock graceful degradation and no logging of which
  stock/day was missing — see Tech debt.

## Local setup

Python 3.11 is what CI uses. (Local dev on 3.14 works but akshare emits noisy
pandas `FutureWarning`s; the export script already suppresses them.)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run the FastAPI app:

```bash
uvicorn app.main:app --reload      # http://127.0.0.1:8000
```

Send a test email (needs a local `.env`, see below):

```bash
python3 scripts/send_email_report.py
```

Export the spreadsheet locally (needs `openpyxl` installed — not in
requirements.txt yet):

```bash
pip install openpyxl
python3 scripts/export_report_xlsx.py
```

> The data source only works from a machine that can reach the exchange
> endpoints. It runs slowly from outside China (see timeout note below).

## Configuration

In `app/services/stocks.py`:

- `TRADING_DAY_WINDOW = 10` — number of complete trading days per report.
- `MAX_LOOKBACK_DAYS = 45` — how far back to search for those days.
- `CACHE_TTL_MINUTES = 15`, `CACHE_SCHEMA_VERSION` — see Caching. Bump the
  schema version if you change the cached payload shape or fetch semantics.

Environment variables:

- `MARGIN_FETCH_TIMEOUT` (optional, seconds) — per-request network timeout.
  **Off by default on purpose.** The exchange requests are slow but do complete
  from GitHub's overseas runners; an aggressive timeout makes every fetch time
  out and yields "0 complete days". Only set this for local runs if you want a
  hang ceiling.
- SMTP vars for the email path: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`,
  `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_TO`, `SMTP_USE_SSL`,
  `REPORT_SUBJECT_PREFIX`. Locally these live in `.env` (git-ignored); in CI
  they are GitHub Actions repository secrets. `.env.example` is the template.

## Caching

`get_margin_dashboard()` caches to `.cache/margin_dashboard.json` for 15
minutes. The cache key includes `CACHE_SCHEMA_VERSION` and the full watchlist,
so **editing `tracked_stocks.json` automatically invalidates the cache.** Force
a refresh with `rm -f .cache/margin_dashboard.json` or the dashboard's
`POST /api/margin-dashboard/clear-cache`.

## GitHub Actions (production)

The workflow in `.github/workflows/` ("Daily Email Report") runs the email
script daily at `07 1 * * *` UTC (09:07 Asia/Shanghai) and supports manual runs
via `workflow_dispatch`. It checks out `main`, installs `requirements.txt`, and
runs `scripts/send_email_report.py` with the SMTP secrets injected as env vars.

**The cron always runs the current `main`.** Any change (watchlist, fetch logic,
report format) only takes effect once pushed to `main`. To verify a change,
trigger the workflow manually from the Actions tab.

There is no failure alerting: a broken run only shows up as a missing email.
Consider enabling GitHub's Actions failure notifications.

## Editing the watchlist (`data/tracked_stocks.json`)

Each entry: `{"symbol": "600428", "name": "中远海特", "market": "SSE"}`.

- `market` must be `SSE` (codes starting 6) or `SZSE` (codes starting 0/3).
- The stock **must be margin-eligible** (see The hard contract).
- After editing, the next run picks it up; push to `main` for the daily email.

Validate before pushing:

```bash
python3 -c "import json; d=json.load(open('data/tracked_stocks.json')); \
print(len(d), 'ok' if all(x['market'] in ('SSE','SZSE') for x in d) else 'BAD market')"
```

## Maintenance playbook

- **Add/remove a stock:** edit `tracked_stocks.json`, verify market + margin
  eligibility, commit, push, trigger the workflow to confirm.
- **Daily job fails with "Only found N complete trading days":** almost always a
  watchlist member that isn't margin-eligible or is suspended, OR a transient
  data-source outage. Bisect by temporarily removing recently-added stocks.
- **Change the reporting window:** edit `TRADING_DAY_WINDOW` (and bump
  `CACHE_SCHEMA_VERSION`).
- **akshare returns empty for all dates:** check whether the exchange endpoints
  or column names changed; do NOT assume it's the network without checking.

## Tech debt / known gaps (please address when handing off)

- **No automated tests.** The fragile parts (SSE/SZSE row parsing,
  `balance_scope` logic, 5/10-day change math, the backward-walk date
  selection) have no committed tests. Adding `tests/` is the highest-value next
  step. Historically changes were verified with throwaway mock scripts.
- **Spreadsheet path not in repo.** `scripts/export_report_xlsx.py` and
  `openpyxl` in `requirements.txt` exist locally but are uncommitted. Decide:
  commit them, or document the feature as intentionally local-only.
- **Dead code.** `MOCK_MARGIN_DATA` and `_build_mock_dashboard()` in
  `stocks.py` are unused — the live path raises instead of falling back to mock.
  Remove or clearly mark deprecated to avoid misleading readers.
- **No observability.** Add structured logging (which dates fetched, which
  symbol/day missing) so failures are diagnosable.
- **No watchlist eligibility check in CI.** A bad stock silently breaks the cron
  a day later. A pre-commit/CI validator would catch it early.
- **README drift.** The API section still shows a hardcoded 5-stock example and
  doesn't mention the spreadsheet path or `MARGIN_FETCH_TIMEOUT`.

## Conventions for AI agents working here

- This is a personal investment tool. **Never fabricate financial data,
  prices, balances, or dates.** If the live source is unavailable, surface that
  — do not invent numbers or silently fall back to mock data.
- Verify code changes against the data contract above before claiming they work.
  You cannot rely on the CI network reaching the CN exchanges from every
  environment, so unit-test parsing/logic with mocked akshare responses.
- Keep the reports (email and spreadsheet) consistent with each other when
  changing metrics or windows.
