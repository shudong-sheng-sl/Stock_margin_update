from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
import socket
from pathlib import Path
from typing import Any
from typing import Optional

from app.models import MarginDashboardResponse, MarginRecord, MarginStockSeries


@dataclass(frozen=True)
class TrackedStock:
    symbol: str
    name: str
    market: str


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = BASE_DIR / ".cache"
TRACKED_STOCKS_FILE = DATA_DIR / "tracked_stocks.json"
CACHE_FILE = CACHE_DIR / "margin_dashboard.json"
CACHE_TTL_MINUTES = 15
CACHE_SCHEMA_VERSION = "v9"
TRADING_DAY_WINDOW = 10
NETWORK_TIMEOUT_SECONDS = 20
MAX_LOOKBACK_DAYS = 45

MOCK_MARGIN_DATA: dict[str, list[dict[str, float | str]]] = {
    "600428": [
        {"trading_date": "2026-03-25", "financing_balance": 522300000.0, "securities_balance": 12400000.0},
        {"trading_date": "2026-03-26", "financing_balance": 526800000.0, "securities_balance": 12180000.0},
        {"trading_date": "2026-03-27", "financing_balance": 518600000.0, "securities_balance": 12090000.0},
        {"trading_date": "2026-03-30", "financing_balance": 515200000.0, "securities_balance": 11870000.0},
        {"trading_date": "2026-03-31", "financing_balance": 520600000.0, "securities_balance": 11940000.0},
    ],
    "600585": [
        {"trading_date": "2026-03-25", "financing_balance": 1408000000.0, "securities_balance": 33800000.0},
        {"trading_date": "2026-03-26", "financing_balance": 1415000000.0, "securities_balance": 34100000.0},
        {"trading_date": "2026-03-27", "financing_balance": 1402000000.0, "securities_balance": 33600000.0},
        {"trading_date": "2026-03-30", "financing_balance": 1394000000.0, "securities_balance": 33200000.0},
        {"trading_date": "2026-03-31", "financing_balance": 1401000000.0, "securities_balance": 33500000.0},
    ],
    "600160": [
        {"trading_date": "2026-03-25", "financing_balance": 980000000.0, "securities_balance": 27600000.0},
        {"trading_date": "2026-03-26", "financing_balance": 989000000.0, "securities_balance": 27900000.0},
        {"trading_date": "2026-03-27", "financing_balance": 975000000.0, "securities_balance": 27200000.0},
        {"trading_date": "2026-03-30", "financing_balance": 970000000.0, "securities_balance": 26800000.0},
        {"trading_date": "2026-03-31", "financing_balance": 978000000.0, "securities_balance": 27100000.0},
    ],
    "601117": [
        {"trading_date": "2026-03-25", "financing_balance": 1160000000.0, "securities_balance": 21800000.0},
        {"trading_date": "2026-03-26", "financing_balance": 1172000000.0, "securities_balance": 22000000.0},
        {"trading_date": "2026-03-27", "financing_balance": 1165000000.0, "securities_balance": 21900000.0},
        {"trading_date": "2026-03-30", "financing_balance": 1156000000.0, "securities_balance": 21500000.0},
        {"trading_date": "2026-03-31", "financing_balance": 1163000000.0, "securities_balance": 21700000.0},
    ],
    "000333": [
        {"trading_date": "2026-03-25", "financing_balance": 2280000000.0, "securities_balance": 45200000.0},
        {"trading_date": "2026-03-26", "financing_balance": 2295000000.0, "securities_balance": 45900000.0},
        {"trading_date": "2026-03-27", "financing_balance": 2279000000.0, "securities_balance": 44800000.0},
        {"trading_date": "2026-03-30", "financing_balance": 2268000000.0, "securities_balance": 44300000.0},
        {"trading_date": "2026-03-31", "financing_balance": 2276000000.0, "securities_balance": 44600000.0},
    ],
}


def get_margin_dashboard() -> MarginDashboardResponse:
    tracked_stocks = _load_tracked_stocks()
    cached_dashboard = _read_cached_dashboard(tracked_stocks)
    if cached_dashboard is not None:
        return cached_dashboard

    live_stocks = _load_live_margin_dashboard(tracked_stocks)
    if live_stocks:
        latest_date = _find_latest_trading_date(live_stocks)
        dashboard = MarginDashboardResponse(
            provider="AKShare",
            sources=[
                "Shanghai Stock Exchange margin detail",
                "Shenzhen Stock Exchange margin detail",
            ],
            latest_trading_date=latest_date,
            stocks=live_stocks,
        )
        _write_cached_dashboard(dashboard, tracked_stocks)
        return dashboard

    raise RuntimeError(
        "Live data is unavailable. The dashboard is configured to require exchange-backed live data."
    )


def clear_margin_dashboard_cache() -> bool:
    try:
        CACHE_FILE.unlink()
    except FileNotFoundError:
        return False
    return True


def _load_live_margin_dashboard(tracked_stocks: list[TrackedStock]) -> list[MarginStockSeries]:
    if not tracked_stocks:
        raise RuntimeError("No tracked stocks are configured.")

    # Prevent any single exchange request from hanging indefinitely.
    socket.setdefaulttimeout(NETWORK_TIMEOUT_SECONDS)

    symbols = {stock.symbol for stock in tracked_stocks}
    detail_by_date: dict[str, dict[str, dict[str, Any]]] = {}
    complete_dates: list[str] = []

    # Walk backward from today, fetching each trading day's margin detail exactly
    # once, and keep only days where every tracked stock has a row. Stop as soon
    # as we have the most recent TRADING_DAY_WINDOW complete days. This avoids the
    # previous approach of downloading the full exchange tables twice per day
    # across a 30-day window.
    for offset in range(0, MAX_LOOKBACK_DAYS):
        if len(complete_dates) >= TRADING_DAY_WINDOW:
            break
        candidate = date.today() - timedelta(days=offset)
        if candidate.weekday() >= 5:  # skip weekends; exchanges are closed
            continue
        trading_day = candidate.strftime("%Y%m%d")
        rows = _load_margin_detail_for_date(trading_day)
        if not rows:
            continue
        if symbols.issubset(rows.keys()):
            detail_by_date[trading_day] = rows
            complete_dates.append(trading_day)

    if len(complete_dates) < TRADING_DAY_WINDOW:
        raise RuntimeError(
            f"Only found {len(complete_dates)} complete trading days where all tracked "
            f"stocks had margin rows within the last {MAX_LOOKBACK_DAYS} days; "
            f"expected {TRADING_DAY_WINDOW}. A tracked stock may be newly added, "
            f"suspended, or not margin-eligible."
        )

    trading_dates = sorted(complete_dates)  # ascending: oldest -> newest

    price_history = _load_price_history(tracked_stocks, trading_dates)

    stock_series: list[MarginStockSeries] = []
    for stock in tracked_stocks:
        records = _build_stock_records(
            stock,
            trading_dates,
            detail_by_date,
            price_history,
        )
        if len(records) != TRADING_DAY_WINDOW:
            raise RuntimeError(
                f"Incomplete live records for {stock.symbol} {stock.name}; expected {TRADING_DAY_WINDOW} rows, got {len(records)}."
            )
        stock_scope = _stock_balance_scope(records)
        stock_series.append(
            MarginStockSeries(
                symbol=stock.symbol,
                name=stock.name,
                market=stock.market,
                balance_scope=stock_scope,
                records=records,
            )
        )

    return stock_series


def _load_margin_detail_for_date(trading_day: str) -> dict[str, dict[str, Any]]:
    try:
        import akshare as ak
    except Exception:
        return {}

    detail_rows: dict[str, dict[str, Any]] = {}

    try:
        sse_df = ak.stock_margin_detail_sse(date=trading_day)
    except Exception:
        sse_df = None

    if sse_df is not None and not sse_df.empty:
        for row in sse_df.to_dict(orient="records"):
            symbol = _to_string(row.get("标的证券代码"))
            if symbol:
                detail_rows[symbol] = row

    try:
        szse_df = ak.stock_margin_detail_szse(date=trading_day)
    except Exception:
        szse_df = None

    if szse_df is not None and not szse_df.empty:
        for row in szse_df.to_dict(orient="records"):
            symbol = _to_string(row.get("证券代码"))
            if symbol:
                detail_rows[symbol] = row

    return detail_rows


def _build_stock_records(
    stock: TrackedStock,
    trading_dates: list[str],
    detail_by_date: dict[str, dict[str, dict[str, Any]]],
    price_history: dict[tuple[str, str], dict[str, float]],
) -> list[MarginRecord]:
    records: list[MarginRecord] = []
    previous_financing = 0.0
    previous_securities: Optional[float] = None
    previous_margin: Optional[float] = None

    for index, trading_day in enumerate(trading_dates):
        row = detail_by_date.get(trading_day, {}).get(stock.symbol)
        if row is None:
            raise RuntimeError(
                f"Missing live margin row for {stock.symbol} {stock.name} on {trading_day}."
            )
        price_snapshot = price_history.get((stock.symbol, trading_day), {})
        close_price = _optional_float(price_snapshot.get("close_price"))
        price_change_percent = _optional_float(price_snapshot.get("price_change_percent"))

        financing_balance = _extract_financing_balance(row)
        securities_balance = _extract_securities_balance(row=row)
        margin_balance = _extract_margin_balance(row, financing_balance, securities_balance)
        balance_scope = _determine_balance_scope(
            securities_balance=securities_balance,
            margin_balance=margin_balance,
        )

        record = MarginRecord(
            trading_date=_format_trading_date(trading_day),
            close_price=close_price,
            price_change_percent=price_change_percent,
            financing_balance=financing_balance,
            financing_change_percent=_change_percent(
                current=financing_balance,
                previous=previous_financing,
                index=index,
            ),
            securities_balance=securities_balance,
            margin_balance=margin_balance,
            financing_change=0.0 if index == 0 else financing_balance - previous_financing,
            securities_change=_optional_change(
                current=securities_balance,
                previous=previous_securities,
                index=index,
            ),
            margin_change=_optional_change(
                current=margin_balance,
                previous=previous_margin,
                index=index,
            ),
            balance_scope=balance_scope,
        )
        records.append(record)

        previous_financing = financing_balance
        previous_securities = securities_balance
        previous_margin = margin_balance

    return records


def _build_mock_dashboard(tracked_stocks: list[TrackedStock]) -> list[MarginStockSeries]:
    stock_series: list[MarginStockSeries] = []

    for stock in tracked_stocks:
        raw_records = MOCK_MARGIN_DATA.get(stock.symbol)
        fallback_records = _generate_mock_records(stock)
        if raw_records is None:
            raw_records = fallback_records
        else:
            raw_by_date = {
                _to_string(record.get("trading_date")): record for record in raw_records
            }
            raw_records = [
                raw_by_date.get(
                    _to_string(record.get("trading_date")),
                    record,
                )
                for record in fallback_records
            ]
        records: list[MarginRecord] = []
        previous_financing = 0.0
        previous_securities: Optional[float] = None
        previous_margin: Optional[float] = None

        for index, raw_record in enumerate(raw_records):
            fallback_record = fallback_records[index]
            financing_balance = _to_float(raw_record.get("financing_balance"))
            securities_balance = _to_float(raw_record.get("securities_balance"))
            margin_balance = financing_balance + securities_balance
            balance_scope = "full_margin"
            close_price = _to_float(
                raw_record.get("close_price", fallback_record.get("close_price"))
            )
            price_change_percent = _to_float(
                raw_record.get(
                    "price_change_percent",
                    fallback_record.get("price_change_percent"),
                )
            )

            records.append(
                MarginRecord(
                    trading_date=_to_string(raw_record.get("trading_date")),
                    close_price=close_price,
                    price_change_percent=price_change_percent,
                    financing_balance=financing_balance,
                    financing_change_percent=_change_percent(
                        current=financing_balance,
                        previous=previous_financing,
                        index=index,
                    ),
                    securities_balance=securities_balance,
                    margin_balance=margin_balance,
                    financing_change=0.0 if index == 0 else financing_balance - previous_financing,
                    securities_change=_optional_change(
                        current=securities_balance,
                        previous=previous_securities,
                        index=index,
                    ),
                    margin_change=_optional_change(
                        current=margin_balance,
                        previous=previous_margin,
                        index=index,
                    ),
                    balance_scope=balance_scope,
                )
            )

            previous_financing = financing_balance
            previous_securities = securities_balance
            previous_margin = margin_balance

        stock_series.append(
            MarginStockSeries(
                symbol=stock.symbol,
                name=stock.name,
                market=stock.market,
                balance_scope="full_margin",
                records=records,
            )
        )

    return stock_series


def _extract_financing_balance(row: dict[str, Any]) -> float:
    if "融资余额" in row:
        return _to_float(row.get("融资余额"))
    return 0.0


def _extract_securities_balance(row: dict[str, Any]) -> Optional[float]:
    if "融券余额" in row:
        return _to_float(row.get("融券余额"))
    for key in ("融券余量金额", "融券余量金额(元)", "融券卖出额"):
        if key in row:
            return _to_float(row.get(key))
    return None


def _extract_margin_balance(
    row: dict[str, Any],
    financing_balance: float,
    securities_balance: Optional[float],
) -> Optional[float]:
    if "融资融券余额" in row:
        margin_balance = _to_float(row.get("融资融券余额"))
        if margin_balance > 0:
            return margin_balance
    if securities_balance is not None:
        return financing_balance + securities_balance
    return None


def _find_latest_trading_date(stocks: list[MarginStockSeries]) -> Optional[str]:
    all_dates = [record.trading_date for stock in stocks for record in stock.records]
    if not all_dates:
        return None
    return max(all_dates)


def _format_trading_date(trading_day: str) -> str:
    try:
        parsed = datetime.strptime(trading_day, "%Y%m%d")
        return parsed.strftime("%Y-%m-%d")
    except ValueError:
        return trading_day


def _load_tracked_stocks() -> list[TrackedStock]:
    try:
        raw_items = json.loads(TRACKED_STOCKS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _default_tracked_stocks()
    except json.JSONDecodeError:
        return _default_tracked_stocks()

    tracked_stocks: list[TrackedStock] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        symbol = _to_string(item.get("symbol"))
        name = _to_string(item.get("name"))
        market = _to_string(item.get("market")).upper()
        if not symbol or not name or market not in {"SSE", "SZSE"}:
            continue
        tracked_stocks.append(TrackedStock(symbol=symbol, name=name, market=market))

    return tracked_stocks or _default_tracked_stocks()


def _default_tracked_stocks() -> list[TrackedStock]:
    return [
        TrackedStock(symbol="600428", name="中远海特", market="SSE"),
        TrackedStock(symbol="600585", name="海螺水泥", market="SSE"),
        TrackedStock(symbol="600160", name="巨化股份", market="SSE"),
        TrackedStock(symbol="601117", name="中国化学", market="SSE"),
        TrackedStock(symbol="000333", name="美的集团", market="SZSE"),
    ]


def _generate_mock_records(stock: TrackedStock) -> list[dict[str, float | str]]:
    base_seed = sum(ord(char) for char in stock.symbol)
    start_financing = 300000000.0 + (base_seed % 80) * 10000000.0
    start_securities = 5000000.0 + (base_seed % 20) * 500000.0
    dates = _recent_mock_trading_dates(TRADING_DAY_WINDOW)
    records: list[dict[str, float | str]] = []

    for index, trading_date in enumerate(dates):
        direction = 1 if index % 2 == 0 else -1
        financing_balance = start_financing + direction * index * 4200000.0
        securities_balance = start_securities + direction * index * 180000.0
        close_price = 8.0 + (base_seed % 300) / 10 + direction * index * 0.18
        price_change_percent = 0.0 if index == 0 else direction * (0.85 + index * 0.22)
        records.append(
            {
                "trading_date": trading_date,
                "close_price": round(close_price, 2),
                "price_change_percent": round(price_change_percent, 2),
                "financing_balance": financing_balance,
                "securities_balance": securities_balance,
            }
        )

    return records


def _recent_mock_trading_dates(limit: int) -> list[str]:
    dates: list[str] = []
    candidate = date.today() - timedelta(days=1)

    while len(dates) < limit:
        if candidate.weekday() < 5:
            dates.append(candidate.strftime("%Y-%m-%d"))
        candidate -= timedelta(days=1)

    return sorted(dates)


def _read_cached_dashboard(
    tracked_stocks: list[TrackedStock],
) -> Optional[MarginDashboardResponse]:
    try:
        raw_cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return None

    expires_at = _to_string(raw_cache.get("expires_at"))
    if not expires_at or _is_cache_expired(expires_at):
        return None

    cache_key = _to_string(raw_cache.get("cache_key"))
    if cache_key != _cache_key_for_stocks(tracked_stocks):
        return None

    payload = raw_cache.get("payload")
    if not isinstance(payload, dict):
        return None

    try:
        dashboard = MarginDashboardResponse(**payload)
    except Exception:
        return None

    provider = dashboard.provider
    if provider != "Mock fallback":
        provider = f"{provider} (cached)"

    return MarginDashboardResponse(
        provider=provider,
        sources=dashboard.sources,
        latest_trading_date=dashboard.latest_trading_date,
        stocks=dashboard.stocks,
    )


def _write_cached_dashboard(
    dashboard: MarginDashboardResponse, tracked_stocks: list[TrackedStock]
) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    expires_at = datetime.utcnow() + timedelta(minutes=CACHE_TTL_MINUTES)
    payload = {
        "expires_at": expires_at.isoformat(),
        "cache_key": _cache_key_for_stocks(tracked_stocks),
        "payload": _serialize_dashboard(dashboard),
    }
    CACHE_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _is_cache_expired(expires_at: str) -> bool:
    try:
        parsed = datetime.fromisoformat(expires_at)
    except ValueError:
        return True
    return datetime.utcnow() >= parsed


def _cache_key_for_stocks(tracked_stocks: list[TrackedStock]) -> str:
    stocks_key = "|".join(
        f"{stock.symbol}:{stock.name}:{stock.market}" for stock in tracked_stocks
    )
    return f"{CACHE_SCHEMA_VERSION}|{stocks_key}"


def _serialize_dashboard(dashboard: MarginDashboardResponse) -> dict[str, Any]:
    if hasattr(dashboard, "model_dump"):
        return dashboard.model_dump()
    return dashboard.dict()


def _optional_change(
    current: Optional[float], previous: Optional[float], index: int
) -> Optional[float]:
    if current is None:
        return None
    if index == 0 or previous is None:
        return 0.0
    return current - previous


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _change_percent(current: float, previous: float, index: int) -> float:
    if index == 0 or previous == 0:
        return 0.0
    return ((current - previous) / previous) * 100


def _determine_balance_scope(
    securities_balance: Optional[float], margin_balance: Optional[float]
) -> str:
    if securities_balance is not None or margin_balance is not None:
        return "full_margin"
    return "financing_only"


def _stock_balance_scope(records: list[MarginRecord]) -> str:
    if any(record.balance_scope == "financing_only" for record in records):
        return "financing_only"
    return "full_margin"


def _load_price_history(
    tracked_stocks: list[TrackedStock],
    trading_dates: list[str],
) -> dict[tuple[str, str], dict[str, float]]:
    if not trading_dates:
        return {}

    start_date = trading_dates[0]
    end_date = trading_dates[-1]
    history: dict[tuple[str, str], dict[str, float]] = {}

    for stock in tracked_stocks:
        em_history = _load_price_history_from_eastmoney(stock, start_date, end_date)
        tx_history = _load_price_history_from_tencent(stock, start_date, end_date)
        merged_history = _merge_price_history(em_history, tx_history)

        for trading_day, snapshot in merged_history.items():
            history[(stock.symbol, trading_day)] = snapshot

    return history


def _load_price_history_from_eastmoney(
    stock: TrackedStock, start_date: str, end_date: str
) -> dict[str, dict[str, float]]:
    try:
        import akshare as ak
    except Exception:
        return {}

    try:
        dataframe = ak.stock_zh_a_hist(
            symbol=stock.symbol,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="",
        )
    except Exception:
        return {}

    if dataframe is None or dataframe.empty:
        return {}

    history: dict[str, dict[str, float]] = {}
    for row in dataframe.to_dict(orient="records"):
        trading_day = _normalize_hist_date(row.get("日期"))
        if not trading_day:
            continue
        history[trading_day] = {
            "close_price": _to_float(row.get("收盘")),
            "price_change_percent": _to_float(row.get("涨跌幅")),
        }

    return history


def _load_price_history_from_tencent(
    stock: TrackedStock, start_date: str, end_date: str
) -> dict[str, dict[str, float]]:
    try:
        import akshare as ak
    except Exception:
        return {}

    try:
        dataframe = ak.stock_zh_a_hist_tx(
            symbol=_tx_hist_symbol(stock),
            start_date=start_date,
            end_date=end_date,
            adjust="",
        )
    except Exception:
        return {}

    if dataframe is None or dataframe.empty:
        return {}

    rows = dataframe.to_dict(orient="records")
    history: dict[str, dict[str, float]] = {}
    previous_close: Optional[float] = None

    for row in rows:
        trading_day = _normalize_hist_date(row.get("date"))
        close_price = _optional_float(row.get("close"))
        if not trading_day or close_price is None:
            continue

        price_change_percent = 0.0
        if previous_close not in (None, 0.0):
            price_change_percent = ((close_price - previous_close) / previous_close) * 100

        history[trading_day] = {
            "close_price": close_price,
            "price_change_percent": price_change_percent,
        }
        previous_close = close_price

    return history


def _merge_price_history(
    primary_history: dict[str, dict[str, float]],
    fallback_history: dict[str, dict[str, float]],
) -> dict[str, dict[str, float]]:
    merged = dict(fallback_history)
    merged.update(primary_history)
    return merged


def _tx_hist_symbol(stock: TrackedStock) -> str:
    prefix = "sh" if stock.market == "SSE" else "sz"
    return f"{prefix}{stock.symbol}"
def _normalize_hist_date(value: Any) -> str:
    if value is None:
        return ""

    text = _to_string(value)
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d")
        return parsed.strftime("%Y%m%d")
    except ValueError:
        return text.replace("-", "")


def _to_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
