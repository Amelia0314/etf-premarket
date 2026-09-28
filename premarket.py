import os
from datetime import datetime, timezone, timedelta

import requests
import akshare as ak
import yfinance as yf

WEBHOOK = os.environ.get("WECHAT_WEBHOOK_URL")
BJ_TZ = timezone(timedelta(hours=8))
WEEKDAY_CN = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


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
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="5d", interval="1d")
        if hist is None or len(hist) < 2:
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


def fetch_etf():
    targets = {"159915": "创业板ETF", "588000": "科创50ETF", "510500": "中证500ETF"}
    try:
        df = ak.fund_etf_spot_em()
        result = []
        for code, name in targets.items():
            row = df[df['代码'] == code]
            if row.empty:
                continue
            r = row.iloc[0]
            result.append({
                "code": code,
                "name": name,
                "price": float(r['最新价']),
                "change_pct": float(r['涨跌幅']),
            })
        return result
    except Exception as e:
        print(f"ETF 获取失败: {e}")
        return []


def fetch_option_pcr():
    result = {}
    now = datetime.now(BJ_TZ)
    current_month = now.strftime("%y%m")
    next_month = (now.replace(day=1) + timedelta(days=32)).strftime("%y%m")
    months = [current_month, next_month]

   targets = [
    ("南方中证500ETF期权", "中证500ETF期权"),
    ("易方达创业板ETF期权", "创业板ETF期权"),
       ("华夏科创50ETF期权", "科创50ETF期权")
]
    for symbol, label in targets:
        for m in months:
            try:
                df = ak.option_finance_board(symbol=symbol, end_month=m)
                if df is None or df.empty:
                    continue
                call_vol = df[df['看涨看跌'] == '看涨']['成交量'].sum()
                put_vol = df[df['看涨看跌'] == '看跌']['成交量'].sum()
                if call_vol > 0:
                    result[label] = {
                        "pcr": put_vol / call_vol,
                        "call_vol": int(call_vol),
                        "put_vol": int(put_vol),
                    }
                    break
            except Exception as e:
                print(f"{symbol} {m} 获取失败: {e}")
    return result


def format_pct(pct):
    if pct >= 0:
        return f"**+{pct:.2f}%**"
    return f"{pct:.2f}%"


def build_message(us_data, asia_data, etf_data, option_data):
    now = datetime.now(BJ_TZ)
    date_str = now.strftime("%Y-%m-%d") + " " + WEEKDAY_CN[now.weekday()]

    L = []
    L.append("# 📊 ETF期权盘前概览")
    L.append(f"**日期：{date_str}**")
    L.append("")
    L.append("—————————————")
    L.append("")

    L.append("## 🌙 隔夜美股（前收盘）")
    L.append("")
    if us_data:
        for item in us_data:
            L.append(f"- **{item['label']}**：收于 {item['price']:.2f}，涨跌幅 {format_pct(item['change_pct'])}")
    else:
        L.append("- 数据获取失败")
    L.append("")

    L.append("## 🌏 亚太早盘（实时）")
    L.append("")
    if asia_data:
        for item in asia_data:
            L.append(f"- **{item['label']}**：{item['price']:.2f}，涨跌幅 {format_pct(item['change_pct'])}")
    else:
        L.append("- 数据获取失败")
    L.append("")

    L.append("## 🇨🇳 A股核心标的（前收盘）")
    L.append("")
    if etf_data:
        for item in etf_data:
            L.append(
                f"- **{item['name']}（{item['code']}）**：{item['price']:.3f}，涨跌幅 {format_pct(item['change_pct'])}"
            )
    else:
        L.append("- 数据获取失败")
    L.append("")

    L.append("## ⚠️ 期权波动率提示")
    L.append("")
    if option_data:
        for label, info in option_data.items():
            L.append(
                f"- **{label}**：成交量PCR {info['pcr']:.2f}"
                f"（看涨 {info['call_vol']} / 看跌 {info['put_vol']}）"
            )
        L.append("- 平值IV 暂未计算，可后续用 Black-Scholes 反推")
    else:
        L.append("- 期权数据暂不可用")
    L.append("")

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

    print("开始抓取数据...")

    us_data = [fetch_yf("SPY", "SPY（标普500）"), fetch_yf("QQQ", "QQQ（纳斯达克100）")]
    us_data = [x for x in us_data if x]

    asia_data = [fetch_yf("^N225", "日经225"), fetch_yf("^KS11", "KOSPI")]
    asia_data = [x for x in asia_data if x]

    etf_data = fetch_etf()
    option_data = fetch_option_pcr()

    msg = build_message(us_data, asia_data, etf_data, option_data)
    print("=" * 60)
    print(msg)
    print("=" * 60)

    push_wecom(msg)


if __name__ == "__main__":
    main()
