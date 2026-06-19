"""
铠侠(285A) 盘中实时监控
GitHub Actions 每5分钟触发一次，交易时间外自动跳过。

关键设计（修正版）：
- 不只看"当下这一瞬间"的价格，而是用 Yahoo 已经返回的【当日最高/最低】
  来算"今天最大波动"。这样即使 GitHub 把定时任务限流/延迟、采样很稀疏，
  只要有一次跑到，也能补报当天发生过的大波动，不会再漏。
- 时间窗放宽到 JST 9:00–17:30：收盘是 15:30，但 GitHub 的定时任务经常
  延迟一两小时才跑，放宽后这些"迟到"的任务还能把当天行情补报给你。
"""
import urllib.request, urllib.parse, json, datetime, os, sys

# ===== 预警阈值（按需调整）=====
NOTICE_PCT = 3.0   # 🟡 注意：当日波动达到 ±3%
URGENT_PCT = 6.0   # 🔴 紧急：当日波动达到 ±6%

def jst_now():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=9)

def is_trading(t):
    # 周末不交易；JST 9:00–17:30（收盘15:30，留缓冲让被延迟的定时任务也能补报）
    if t.weekday() >= 5:
        return False
    m = t.hour * 60 + t.minute
    return 9 * 60 <= m <= 17 * 60 + 30

def fetch_price():
    url = "https://query1.finance.yahoo.com/v8/finance/chart/285A.T?interval=1m&range=1d&includePrePost=false"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        meta = json.loads(r.read())["chart"]["result"][0]["meta"]
    return (
        meta["regularMarketPrice"],
        meta["chartPreviousClose"],     # 昨日收盘价 → 官方涨跌幅基准
        meta["regularMarketDayHigh"],   # 当日最高
        meta["regularMarketDayLow"],    # 当日最低
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
        price, prev, high, low = fetch_price()
    except Exception as e:
        print(f"股价获取失败: {e}")
        sys.exit(1)

    cur  = (price - prev) / prev * 100   # 现价相对昨收
    up   = (high  - prev) / prev * 100   # 当日最高涨幅
    down = (low   - prev) / prev * 100   # 当日最低跌幅（负数）

    # 今天发生过的最大波动（取涨/跌里绝对值更大的那个）
    if up >= -down:
        peak, peak_dir = up, "涨"
    else:
        peak, peak_dir = down, "跌"
    peak_abs = abs(peak)

    print(f"285A ¥{price:,} | 昨收 ¥{prev:,} | 现价 {cur:+.2f}% | 当日高 {up:+.2f}% / 低 {down:+.2f}% | 峰值 {peak:+.2f}%")

    if peak_abs < NOTICE_PCT:
        print(f"当日最大波动 {peak:+.2f}%，未达 ±{NOTICE_PCT}% 阈值，无需预警。")
        sys.exit(0)

    sendkey = os.environ["FTQQ_SENDKEY"].strip().lstrip('﻿')
    level   = "🔴" if peak_abs >= URGENT_PCT else "🟡"
    word    = "急涨" if peak > 0 else "急跌"
    urgency = "立即查看！" if peak_abs >= URGENT_PCT else "建议关注"
    sign    = "+" if peak > 0 else ""

    if peak_abs >= URGENT_PCT:
        action = "🔴 重大波动 — 建议尽快查看行情"
    elif peak > 0:
        action = "🟡 当日明显上涨 — 留意是否到了你预设的处理点"
    else:
        action = "🟡 当日明显下跌 — 留意你预设的止损/观察线"

    cur_sign = "+" if cur >= 0 else ""

    title = f"{level} 铠侠(285A) 当日{word} {sign}{peak:.1f}%！{urgency}"
    body  = f"""**铠侠(285A) 盘中预警**
{now:%Y-%m-%d %H:%M} JST

当前价格：¥{price:,.0f}（现价 {cur_sign}{cur:.2f}%）
昨日收盘：¥{prev:,.0f}
今日最高：¥{high:,.0f}（{up:+.2f}%）
今日最低：¥{low:,.0f}（{down:+.2f}%）

**今日最大波动：{sign}{peak:.2f}%**

---

{action}

预警阈值：±{NOTICE_PCT}% 注意 / ±{URGENT_PCT}% 紧急

---
⚠️ 自动播报，数据来自 Yahoo Finance，仅供参考，不构成投资建议。
GitHub Actions 云端监控 · 约每5分钟检查一次"""

    result = send_wechat(sendkey, title, body)
    print(f"微信通知: {result}")

if __name__ == "__main__":
    main()
