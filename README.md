# Chinese Stock Dashboard

A small dashboard project for tracking recent financing balance data for selected Chinese stocks.

## Stack

- Backend: FastAPI
- Frontend: static HTML/CSS/JavaScript
- Data source: `AkShare` with exchange-backed margin detail endpoints and a mock fallback

## Project Structure

```text
app/
  api/
  services/
  static/
data/
  main.py
requirements.txt
README.md
```

## Quick Start

1. Create a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Run the app:

```bash
uvicorn app.main:app --reload
```

4. Open the dashboard:

```text
http://127.0.0.1:8000
```

## Email Report

You can send the current live dashboard data by email with QQ Mail SMTP.

1. Copy the env template:

```bash
cp .env.example .env
```

2. Fill in your QQ Mail SMTP settings in `.env`:

```env
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_USER=your_qq_email@qq.com
SMTP_PASSWORD=your_qq_smtp_auth_code
SMTP_FROM=your_qq_email@qq.com
SMTP_TO=your_receive_email@example.com
SMTP_USE_SSL=true
REPORT_SUBJECT_PREFIX=[融资余额日报]
```

3. Send a test email:

```bash
python3 scripts/send_email_report.py
```

The email contains:
- 汇总表：股票名称、近10日涨跌幅、近10日融资变化
- 明细表：最近10个交易日的收盘价、涨跌幅、融资余额、融资变化

### Daily 9:00 Automation with GitHub Actions

This repo includes `.github/workflows/daily-email-report.yml`.

- It runs every day at `09:00` (Asia/Shanghai), which is `01:00 UTC`.
- You can also trigger it manually from the Actions tab (`workflow_dispatch`).

Set these repository secrets in GitHub:

- `SMTP_HOST` (for QQ Mail: `smtp.qq.com`)
- `SMTP_PORT` (for QQ Mail SSL: `465`)
- `SMTP_USER`
- `SMTP_PASSWORD` (QQ SMTP 授权码)
- `SMTP_FROM`
- `SMTP_TO` (single email or comma-separated list)
- `SMTP_USE_SSL` (`true` recommended)
- `REPORT_SUBJECT_PREFIX` (optional, e.g. `[融资余额日报]`)

## Configurable Stocks

Tracked stocks now live in [data/tracked_stocks.json](/Users/shudongsheng/Stock_rongzi_update/data/tracked_stocks.json).

Each item looks like this:

```json
{
  "symbol": "600428",
  "name": "中远海特",
  "market": "SSE"
}
```

Rules:
- `market` must be `SSE` or `SZSE`
- after editing the file, the next request will use the new stock list

## API

### `GET /api/margin-dashboard`

Returns recent financing balance history for these stocks, using the latest 10 trading days when available:

- 中远海特 `600428`
- 海螺水泥 `600585`
- 巨化股份 `600160`
- 中国化学 `601117`
- 美的集团 `000333`

Response shape:

```json
{
  "provider": "AKShare",
  "sources": [
    "Shanghai Stock Exchange margin detail",
    "Shenzhen Stock Exchange margin detail"
  ],
  "latest_trading_date": "2026-03-31",
  "stocks": [
    {
      "symbol": "600428",
      "name": "中远海特",
      "market": "SSE",
      "records": [
        {
          "trading_date": "2026-03-25",
          "financing_balance": 522300000.0,
          "financing_change_percent": 0.0,
          "securities_balance": 12400000.0,
          "margin_balance": 534700000.0,
          "financing_change": 0.0,
          "securities_change": 0.0,
          "margin_change": 0.0
        }
      ]
    }
  ]
}
```

## Data Source

The live source is designed to be stable and free:

- `AKShare stock_margin_detail_sse(date=...)`
- `AKShare stock_margin_detail_szse(date=...)`

Those wrap daily margin detail data published by:
- Shanghai Stock Exchange
- Shenzhen Stock Exchange

Notes:
- SSE detail may only expose reliable `融资余额`; when the app cannot confirm a reliable `融券余额` or `融资融券余额`, it only displays `融资余额`.
- SZSE detail returns `融资余额`, `融券余额`, and `融资融券余额` more directly.
- Accuracy comes first: the dashboard does not substitute `融资余额` for `融资融券余额`.

Current behavior:
- If `akshare` is installed and the exchange endpoints are reachable, the backend loads the latest 10 trading days automatically.
- If live loading fails, the API now returns an error instead of falling back to local mock data.
- The UI focuses on `融资余额` and shows `融资变化` as percentage vs the previous trading day.

## Local Cache

The app stores a local cache in `.cache/margin_dashboard.json`.

Behavior:
- cache TTL is 15 minutes
- cached data avoids hitting upstream on every dashboard refresh
- changing `data/tracked_stocks.json` automatically invalidates the previous cache

To force a fresh reload immediately:

```bash
rm -f .cache/margin_dashboard.json
```

You can also click the `清缓存并刷新` button in the dashboard UI.

## Next Good Steps

- Add charts for financing balance trends
- Add tests for SSE and SZSE row normalization
- Add a small settings UI for editing tracked stocks in-browser
