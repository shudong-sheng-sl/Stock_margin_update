from pydantic import BaseModel
from typing import Optional


class MarginRecord(BaseModel):
    trading_date: str
    close_price: Optional[float]
    price_change_percent: Optional[float]
    financing_balance: float
    financing_change_percent: float
    securities_balance: Optional[float]
    margin_balance: Optional[float]
    financing_change: float
    securities_change: Optional[float]
    margin_change: Optional[float]
    balance_scope: str


class MarginStockSeries(BaseModel):
    symbol: str
    name: str
    market: str
    balance_scope: str
    records: list[MarginRecord]


class MarginDashboardResponse(BaseModel):
    provider: str
    sources: list[str]
    latest_trading_date: Optional[str]
    stocks: list[MarginStockSeries]
