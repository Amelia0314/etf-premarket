import os
import calendar
from datetime import datetime, timezone, timedelta, date

import requests
import akshare as ak
import yfinance as yf
import numpy as np

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


# ========== 简单行情（美股、亚太、宏观指数） ==========
def fetch_quote(ticker, label, bp_mode=False):
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="5d", interval="1d")
        if hist is None or len(hist) < 2:
            return None
        price = float(hist['Close'].iloc[-1])
        prev = float(hist['Close'].iloc[-2])
        if bp_mode:
            price = price / 10
            prev = prev / 10
            return {"label": label, "price": price, "bp_change": (price - prev) * 100}
        if prev == 0:
            return None
        return {"label": label, "price": price, "change_pct": (price - prev) / prev * 100}
    except Exception as e:
        print(f"{ticker} 失败: {e}")
        return None


# ========== ETF 详细分析 ==========
def analyze_etf(ticker, label):
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="6mo", interval="1d")
        if hist is None or len(hist) < 61:
            return None

        price = float(hist['Close'].iloc[-1])
        prev_close = float(hist['Close'].iloc[-2])
        open_ = float(hist['Open'].iloc[-1])
        high = float(hist['High'].iloc[-1])
        low = float(hist['Low'].iloc[-1])
        change_pct = (price - prev_close) / prev_close * 100
        amplitude = (high - low) / prev_close * 100

        ma5 = float(hist['Close'].rolling(5).mean().iloc[-1])
        ma10 = float(hist['Close'].rolling(10).mean().iloc[-1])
        ma20 = float(hist['Close'].rolling(20).mean().iloc[-1])
        ma60 = float(hist['Close'].rolling(60).mean().iloc[-1])

        closes = hist['Close'].values
        log_ret = np.log(closes[1:] / closes[:-1])
        hv20 = float(np.std(log_ret[-20:], ddof=1) * np.sqrt(252) * 100)
        hv60 = float(np.std(log_ret[-60:], ddof=1) * np.sqrt(252) * 100)

        recent20 = hist['Close'].iloc[-20:]
        low_20 = float(recent20.min())
        high_20 = float(recent20.max())
        pos = (price - low_20) / (high_20 - low_20) * 100 if high_20 > low_20 else 50

        p5 = float(hist['Close'].iloc[-6]) if len(hist) >= 6 else price
        p20 = float(hist['Close'].iloc[-21]) if len(hist) >= 21 else price
        chg_5d = (price - p5) / p5 * 100
        chg_20d = (price - p20) / p20 * 100

        vol_today = float(hist['Volume'].iloc[-1])
        vol_ma5 = float(hist['Volume'].iloc[-6:-1].mean()) if len(hist) >= 6 else vol_today
        vol_ratio = vol_today / vol_ma5 if vol_ma5 > 0 else 1

        return {
            "label": label, "price": price, "change_pct": change_pct,
            "open": open_, "high": high, "low": low, "amplitude": amplitude,
            "ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60,
            "hv20": hv20, "hv60": hv60,
            "low_20": low_20, "high_20": high_20, "pos": pos,
            "chg_5d": chg_5d, "chg_20d": chg_20d, "vol_ratio": vol_ratio,
        }
    except Exception as e:
        print(f"分析 {ticker} 失败: {e}")
        return None


# ========== 期权到期日 ==========
def get_fourth_wednesday(year, month):
    c = calendar.monthcalendar(year, month)
    wednesdays = [w[calendar.WEDNESDAY] for w in c if w[calendar.WEDNESDAY] != 0]
    return date(year, month, wednesdays[3]) if len(wednesdays) >= 4 else None


def get_expiry_info():
    today = datetime.now(BJ_TZ).date()
    result = []
    for offset in [0, 1]:
        y = today.year
        m = today.month + offset
        if m > 12:
            m -= 12
            y += 1
        exp = get_fourth_wednesday(y, m)
        if exp:
            days_left = (exp - today).days
            if days_left >= 0:
                result.append({"date": exp, "days_left": days_left})
    return result


# ========== 格式化工具 ==========
def fmt_pct(pct):
    if pct >= 0:
        return f"**+{pct:.2f}%**"
    return f"{pct:.2f}%"


def arrow(pct):
    return "🔴" if pct >= 0 else "🟢"


# ========== 各区块 ==========
def build_global_block(us_data, asia_data):
    lines = ["## 🌙 隔夜美股（前收盘）", ""]
    if us_data:
        for item in us_data:
            lines.append(f"- **{item['label']}**：{item['price']:.2f}  {fmt_pct(item['change_pct'])}")
    else:
        lines.append("- 数据获取失败")
    lines.append("")
    lines.append("## 🌏 亚太早盘（实时）")
    lines.append("")
    if asia_data:
        for item in asia_data:
            lines.append(f"- **{item['label']}**：{item['price']:.2f}  {fmt_pct(item['change_pct'])}")
    else:
        lines.append("- 数据获取失败")
    lines.append("")
    return "\n".join(lines)


def build_macro_block(macro):
    lines = ["## 🌐 宏观背景", ""]
    if not macro:
        lines.append("- 数据获取失败")
        lines.append("")
        return "\n".join(lines)
    for key, item in macro.items():
        if key == "US10Y":
            bp = item['bp_change']
            bp_str = f"{bp:+.0f}bp"
            lines.append(f"- **美债10Y**：{item['price']:.2f}%  {bp_str}")
        else:
            lines.append(f"- **{item['label']}**：{item['price']:.2f}  {fmt_pct(item['change_pct'])}")
    lines.append("")
    return "\n".join(lines)


def build_etf_detail_block(etf_list, title="A股核心标的"):
    lines = [f"## 🇨🇳 {title}", ""]
    if not etf_list:
        lines.append("- 数据获取失败")
        lines.append("")
        return "\n".join(lines)
    for e in etf_list:
        lines.append(
            f"**{e['label']}**  {e['price']:.3f}  {arrow(e['change_pct'])}{fmt_pct(e['change_pct'])}"
        )
        lines.append(
            f"开{e['open']:.3f} 高{e['high']:.3f} 低{e['low']:.3f}  "
            f"振幅{e['amplitude']:.2f}%  量比{e['vol_ratio']:.2f}"
        )
        lines.append(
            f"MA5={e['ma5']:.3f}  MA10={e['ma10']:.3f}  MA20={e['ma20']:.3f}  MA60={e['ma60']:.3f}"
        )
        lines.append(
            f"HV20={e['hv20']:.1f}%  HV60={e['hv60']:.1f}%  "
            f"20日区间[{e['low_20']:.3f},{e['high_20']:.3f}] 位于{e['pos']:.0f}%"
        )
        lines.append(
            f"近5日{fmt_pct(e['chg_5d'])}  近20日{fmt_pct(e['chg_20d'])}"
        )
        lines.append("")
    return "\n".join(lines)


def build_etf_simple_block(etf_list, title="A股核心标的（午间）"):
    lines = [f"## 🇨🇳 {title}", ""]
    if not etf_list:
        lines.append("- 数据获取失败")
        lines.append("")
        return "\n".join(lines)
    for e in etf_list:
        lines.append(
            f"- **{e['label']}**：{e['price']:.3f}  "
            f"{arrow(e['change_pct'])}{fmt_pct(e['change_pct'])}  "
            f"振幅{e['amplitude']:.2f}%  "
            f"HV20={e['hv20']:.1f}%"
        )
    lines.append("")
    return "\n".join(lines)


def build_expiry_block(expiry_info):
    lines = ["## 📅 期权到期提醒", ""]
    if not expiry_info:
        lines.append("- 数据获取失败")
        lines.append("")
        return "\n".join(lines)
    for info in expiry_info:
        d = info['date']
        days = info['days_left']
        weekday = WEEKDAY_CN[d.weekday()]
        if days == 0:
            lines.append(f"- ⚠️ **{d.month}月期权到期日就在今天**（{weekday}）")
        elif days <= 7:
            lines.append(f"- ⚠️ **{d.month}月期权到期日**：{d.strftime('%m/%d')}（{weekday}），还有 {days} 天")
        else:
            lines.append(f"- {d.month}月期权到期日：{d.strftime('%m/%d')}（{weekday}），还有 {days} 天")
    lines.append("")
    return "\n".join(lines)


def build_message(push_type, us_data, asia_data, macro, etf_list, expiry_info):
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
        L.append(build_macro_block(macro))
        L.append(build_etf_detail_block(etf_list, "A股核心标的（前收盘）"))
        L.append(build_expiry_block(expiry_info))
    elif push_type == "noon":
        L.append(build_etf_simple_block(etf_list))
    elif push_type == "close":
        L.append(build_etf_detail_block(etf_list, "A股核心标的（今日收盘）"))
    elif push_type == "review":
        L.append(build_etf_detail_block(etf_list, "A股核心标的（今日收盘）"))
        L.append(build_expiry_block(expiry_info))

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

    us_data, asia_data, macro = [], [], {}

    if push_type == "morning":
        us_data = [fetch_quote("SPY", "SPY（标普500）"), fetch_quote("QQQ", "QQQ（纳斯达克100）")]
        us_data = [x for x in us_data if x]
        asia_data = [fetch_quote("^N225", "日经225"), fetch_quote("^KS11", "KOSPI")]
        asia_data = [x for x in asia_data if x]

        macro_raw = {
            "VIX": ("^VIX", "VIX"),
            "HSI": ("^HSI", "恒生指数"),
            "DXY": ("DX-Y.NYB", "美元指数"),
            "GOLD": ("GC=F", "黄金"),
            "OIL": ("CL=F", "原油"),
        }
        for key, (ticker, label) in macro_raw.items():
            r = fetch_quote(ticker, label)
            if r:
                macro[key] = r
        us10y = fetch_quote("^TNX", "美债10Y", bp_mode=True)
        if us10y:
            macro["US10Y"] = us10y

    etf_targets = [
        ("159915.SZ", "创业板ETF（159915）"),
        ("588000.SS", "科创50ETF（588000）"),
        ("510500.SS", "中证500ETF（510500）"),
    ]
    etf_list = []
    for ticker, label in etf_targets:
        r = analyze_etf(ticker, label)
        if r:
            etf_list.append(r)

    expiry_info = get_expiry_info() if push_type in ("morning", "review") else []

    msg = build_message(push_type, us_data, asia_data, macro, etf_list, expiry_info)
    print("=" * 60)
    print(msg)
    print("=" * 60)

    push_wecom(msg)


if __name__ == "__main__":
    main()
