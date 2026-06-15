"""
铠侠(285A) 盘中实时监控
GitHub Actions 每5分钟触发一次，交易时间外自动跳过
"""
import urllib.request, urllib.parse, json, datetime, os, sys

def jst_now():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=9)

def is_trading(t):
    if t.weekday() >= 5:
        return False
    m = t.hour * 60 + t.minute
    return (9*60 <= m <= 11*60+30) or (12*60+30 <= m <= 15*60+30)

def fetch_price():
    url = "https://query1.finance.yahoo.com/v8/finance/chart/285A.T?interval=1m&range=1d&includePrePost=false"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        meta = json.loads(r.read())["chart"]["result"][0]["meta"]
    return (
        meta["regularMarketPrice"],
        meta["chartPreviousClose"],   # 昨日収盤価→官方涨跌幅基准
        meta["regularMarketDayHigh"],
        meta["regularMarketDayLow"],
    )

def send_wechat(sendkey, title, body):
    data = urllib.parse.urlencode({"title": title, "desp": body}).encode()
    req = urllib.request.Request(f"https://sctapi.ftqq.com/{sendkey}.send", data=data)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def main():
    now = jst_now()
    print(f"JST: {now:%Y-%m-%d %H:%M} weekday={now.weekday()}")

    if not is_trading(now):
        print("非交易时间，退出。")
        sys.exit(0)

    try:
        price, open_p, high, low = fetch_price()
    except Exception as e:
        print(f"股价获取失败: {e}")
        sys.exit(1)

    change = (price - open_p) / open_p * 100
    print(f"285A ¥{price:,} | 昨收 ¥{open_p:,} | 涨跌 {change:+.2f}%")

    if abs(change) < 4.0:
        print("正常范围，无需预警。")
        sys.exit(0)

    sendkey = os.environ["FTQQ_SENDKEY"].strip().lstrip('﻿')
    level   = "🔴" if abs(change) >= 7 else "🟡"
    sign    = "+" if change > 0 else ""
    word    = "急涨" if change > 0 else "急跌"
    urgency = "立即查看！" if abs(change) >= 7 else "建议关注"

    if abs(change) >= 7:
        action = "🔴 重大波动 — 请立即查看行情，考虑卖出或止损"
    elif change < 0:
        action = "🟡 下跌注意 — 建议确认止损线，考虑是否减仓"
    else:
        action = "🟡 上涨注意 — 可考虑是否到了获利了结的时机"

    title = f"{level} 铠侠(285A) {sign}{change:.1f}% {word}！{urgency}"
    body  = f"""**铠侠(285A) 实时预警**
{now:%Y-%m-%d %H:%M} JST

当前价格：¥{price:,}
昨日收盘：¥{open_p:,}
今日最高：¥{high:,}
今日最低：¥{low:,}
**涨跌幅（vs昨收）：{sign}{change:.2f}%**

---

{action}

正常波动 ±2~3%，今日 {sign}{change:.1f}%（{round(abs(change)/2.5,1)} 倍）
预警阈值：±4% 注意 / ±7% 紧急

---
GitHub Actions 云端监控 · 下次检查约5分钟后"""

    result = send_wechat(sendkey, title, body)
    print(f"微信通知: {result}")

if __name__ == "__main__":
    main()
