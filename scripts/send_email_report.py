from __future__ import annotations

import os
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv

from app.services.stocks import get_margin_dashboard


def format_percent(value: float | None) -> str:
    if value is None:
        return "--"
    prefix = "+" if value > 0 else ""
    return f"{prefix}{value:.2f}%"


def format_price(value: float | None) -> str:
    if value is None:
        return "--"
    return f"{value:.2f}"


def format_currency(value: float | None) -> str:
    if value is None:
        return "--"
    return f"{value:,.0f}"


def calculate_window_change(records: list[object], field_name: str) -> float | None:
    if len(records) < 2:
        return None

    first = getattr(records[0], field_name, None)
    last = getattr(records[-1], field_name, None)
    if first in (None, 0) or last is None:
        return None
    return ((last - first) / first) * 100


def build_html_report() -> tuple[str, str]:
    dashboard = get_margin_dashboard()
    latest_date = dashboard.latest_trading_date or "unknown"
    subject_prefix = os.getenv("REPORT_SUBJECT_PREFIX", "[融资余额日报]")
    subject = f"{subject_prefix} {latest_date}"

    summary_rows: list[str] = []
    detail_sections: list[str] = []

    for stock in dashboard.stocks:
        window_price_change = calculate_window_change(stock.records, "close_price")
        window_financing_change = calculate_window_change(
            stock.records, "financing_balance"
        )

        summary_rows.append(
            f"""
            <tr>
              <td>{stock.name}</td>
              <td>{format_percent(window_price_change)}</td>
              <td>{format_percent(window_financing_change)}</td>
            </tr>
            """
        )

        detail_rows = "".join(
            f"""
            <tr>
              <td>{record.trading_date}</td>
              <td>{format_price(record.close_price)}</td>
              <td>{format_percent(record.price_change_percent)}</td>
              <td>{format_currency(record.financing_balance)}</td>
              <td>{format_percent(record.financing_change_percent)}</td>
            </tr>
            """
            for record in stock.records
        )

        detail_sections.append(
            f"""
            <h3 style="margin:24px 0 8px;">{stock.name} ({stock.symbol})</h3>
            <table style="width:100%; border-collapse:collapse; margin-bottom:20px;">
              <thead>
                <tr>
                  <th style="text-align:left; border-bottom:1px solid #ddd; padding:8px;">交易日</th>
                  <th style="text-align:left; border-bottom:1px solid #ddd; padding:8px;">收盘价</th>
                  <th style="text-align:left; border-bottom:1px solid #ddd; padding:8px;">涨跌幅</th>
                  <th style="text-align:left; border-bottom:1px solid #ddd; padding:8px;">融资余额</th>
                  <th style="text-align:left; border-bottom:1px solid #ddd; padding:8px;">融资变化</th>
                </tr>
              </thead>
              <tbody>{detail_rows}</tbody>
            </table>
            """
        )

    html = f"""
    <html>
      <body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; color:#1f2a33; line-height:1.5;">
        <h1 style="margin-bottom:8px;">融资余额日报</h1>
        <p style="margin-top:0; color:#62727f;">最新交易日: {latest_date}</p>
        <p style="color:#62727f;">数据来源: {' / '.join(dashboard.sources)}</p>

        <h2 style="margin-top:24px;">汇总</h2>
        <table style="width:100%; border-collapse:collapse; margin-bottom:24px;">
          <thead>
            <tr>
              <th style="text-align:left; border-bottom:1px solid #ddd; padding:8px;">股票名称</th>
              <th style="text-align:left; border-bottom:1px solid #ddd; padding:8px;">近10日涨跌幅</th>
              <th style="text-align:left; border-bottom:1px solid #ddd; padding:8px;">近10日融资变化</th>
            </tr>
          </thead>
          <tbody>
            {''.join(summary_rows)}
          </tbody>
        </table>

        <h2>明细</h2>
        {''.join(detail_sections)}
      </body>
    </html>
    """

    return subject, html


def send_email() -> None:
    load_dotenv(ROOT_DIR / ".env")

    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "465"))
    username = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    sender = os.getenv("SMTP_FROM")
    recipients = [
        item.strip() for item in os.getenv("SMTP_TO", "").split(",") if item.strip()
    ]
    use_ssl = os.getenv("SMTP_USE_SSL", "true").lower() == "true"

    required_values = {
        "SMTP_HOST": host,
        "SMTP_USER": username,
        "SMTP_PASSWORD": password,
        "SMTP_FROM": sender,
        "SMTP_TO": ",".join(recipients),
    }
    missing = [key for key, value in required_values.items() if not value]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    subject, html = build_html_report()

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message.attach(MIMEText(html, "html", "utf-8"))

    if use_ssl:
        with smtplib.SMTP_SSL(host, port) as server:
            server.login(username, password)
            server.sendmail(sender, recipients, message.as_string())
    else:
        with smtplib.SMTP(host, port) as server:
            server.starttls()
            server.login(username, password)
            server.sendmail(sender, recipients, message.as_string())


if __name__ == "__main__":
    try:
        send_email()
        print("Email report sent successfully.")
    except Exception as exc:
        print(f"Failed to send email report: {exc}", file=sys.stderr)
        raise
