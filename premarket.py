import os
from datetime import datetime, timezone, timedelta

import requests
import akshare as ak
import yfinance as yf

WEBHOOK = os.environ.get("WECHAT_WEBHOOK_URL")
BJ_TZ = timezone(timedelta(hours=8))
WEEKDAY_CN = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def get_push_type():
    now = datetime.now(BJ_TZ)
    hour = now.hour
    minute = now.minute
    if hour == 9 and minute < 30:
        return "morning"
    if hour == 11 and minute >= 30:
        return "noon"
    if hour == 15:
        return "close"
    if hour >= 16:
        return "review"
    return "morning"


def is_trade_day():
    try:
        df = ak.tool_trade_date_hist_sina()
        today = datetime.now(BJ_TZ).strftime("%Y-%m-%d")
        dates = set(df['trade_date'].astype(str))
        return today in dates
    except Exception as e:
        print(f"交易日判断失败，默认继续: {e}")
        return True


def fetch_yf(ticker, label):
    """统一用 yfinance 拉行情（美股、亚太、A股ETF都走这里）"""
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="5d", interval="1d")
        if hist is None or len(hist) < 2:
            print(f"{ticker} 数据不足")
            return None
        last = hist.iloc[-1]
        prev = hist.iloc[-2]
        price = float(last['Close'])
        prev_close = float(prev['Close'])
        if prev_close == 0:
            return None
        change_pct = (price - prev_close) / prev_close * 100
        return {"label": label, "price": price, "change_pct": change_pct}
    except Exception as e:
        print(f"yfinance {ticker} 失败: {e}")
        return None


def format_pct(pct):
    if pct >= 0:
        return f"**+{pct:.2f}%**"
    return f"{pct:.2f}%"


def build_global_block(us_data, asia_data):
    lines = ["## 🌙 隔夜美股（前收盘）", ""]
    if us_data:
        for item in us_data:
            lines.append(f"- **{item['label']}**：收于 {item['price']:.2f}，涨跌幅 {format_pct(item['change_pct'])}")
    else:
        lines.append("- 数据获取失败")
    lines.append("")
    lines.append("## 🌏 亚太早盘（实时）")
    lines.append("")
    if asia_data:
        for item in asia_data:
            lines.append(f"- **{item['label']}**：{item['price']:.2f}，涨跌幅 {format_pct(item['change_pct'])}")
    else:
        lines.append("- 数据获取失败")
    lines.append("")
    return "\n".join(lines)


def build_etf_block(etf_data, title="A股核心标的"):
    lines = [f"## 🇨🇳 {title}", ""]
    if etf_data:
        for item in etf_data:
            lines.append(
                f"- **{item['label']}**：{item['price']:.3f}，涨跌幅 {format_pct(item['change_pct'])}"
            )
    else:
        lines.append("- 数据获取失败")
    lines.append("")
    return "\n".join(lines)


def build_message(push_type, us_data, asia_data, etf_data):
    now = datetime.now(BJ_TZ)
    date_str = now.strftime("%Y-%m-%d") + " " + WEEKDAY_CN[now.weekday()]

    titles = {
        "morning": "📊 ETF期权盘前概览",
        "noon": "📊 ETF期权午间概览",
        "close": "📊 ETF期权收盘概览",
        "review": "📊 ETF期权盘后复盘",
    }

    L = [f"# {titles.get(push_type, '📊 ETF期权概览')}"]
    L.append(f"**日期：{date_str}**")
    L.append("")
    L.append("—————————————")
    L.append("")

    if push_type == "morning":
        L.append(build_global_block(us_data, asia_data))
        L.append(build_etf_block(etf_data, "A股核心标的（前收盘）"))
    elif push_type == "noon":
        L.append(build_etf_block(etf_data, "A股核心标的（午间）"))
    elif push_type == "close":
        L.append(build_etf_block(etf_data, "A股核心标的（今日收盘）"))
    elif push_type == "review":
        L.append(build_etf_block(etf_data, "A股核心标的（今日收盘）"))

    L.append("—————————————")
    L.append("*由 GitHub Actions 自动生成 · 数据仅供参考*")
    return "\n".join(L)


def push_wecom(content):
    if not WEBHOOK:
        print("未配置 WECHAT_WEBHOOK_URL，跳过推送")
        return
    payload = {"msgtype": "markdown", "markdown": {"content": content}}
    try:
        r = requests.post(WEBHOOK, json=payload, timeout=15)
        print(f"推送状态: {r.status_code}, 响应: {r.text}")
    except Exception as e:
        print(f"推送失败: {e}")


def main():
    if not is_trade_day():
        print("今天非 A 股交易日，跳过推送")
        return

    push_type = get_push_type()
    print(f"当前推送类型: {push_type}")

    us_data = []
    asia_data = []
    if push_type == "morning":
        us_data = [fetch_yf("SPY", "SPY（标普500）"), fetch_yf("QQQ", "QQQ（纳斯达克100）")]
        us_data = [x for x in us_data if x]
        asia_data = [fetch_yf("^N225", "日经225"), fetch_yf("^KS11", "KOSPI")]
        asia_data = [x for x in asia_data if x]

    # A股三大ETF，统一走 yfinance
    etf_targets = [
        ("159915.SZ", "创业板ETF（159915）"),
        ("588000.SS", "科创50ETF（588000）"),
        ("510500.SS", "中证500ETF（510500）"),
    ]
    etf_data = []
    for ticker, label in etf_targets:
        r = fetch_yf(ticker, label)
        if r:
            etf_data.append(r)

    msg = build_message(push_type, us_data, asia_data, etf_data)
    print("=" * 60)
    print(msg)
    print("=" * 60)

    push_wecom(msg)


if __name__ == "__main__":
    main()
