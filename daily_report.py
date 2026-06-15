"""
半导体日报：每个工作日 8:00 AM JST 自动运行
获取美股收盘数据 + 分析 → 微信推送
"""
import urllib.request, urllib.parse, json, datetime, os

def fetch_yahoo(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    meta = data["chart"]["result"][0]["meta"]
    return {
        "price":      meta.get("regularMarketPrice", 0),
        "prev_close": meta.get("chartPreviousClose", 0),
        "change_pct": meta.get("regularMarketChangePercent", 0),
    }

def assess_level(soxx_pct, nvda_pct):
    if soxx_pct <= -2 or abs(nvda_pct) >= 3:
        return "🔴", "重大", "请立即关注持仓风险"
    if abs(soxx_pct) >= 1 or abs(nvda_pct) >= 1.5:
        return "🟡", "注意", "建议今日密切观察"
    return "🟢", "稳定", "市场平稳，正常持有即可"

def kioxia_outlook(soxx_pct, nvda_pct):
    if soxx_pct <= -2:
        return "半导体板块整体承压，铠侠开盘可能跟跌，建议确认止损线。"
    if soxx_pct >= 2:
        return "半导体板块强势，铠侠有望跟涨，可持股观望。"
    if soxx_pct <= -1:
        return "半导体小幅下跌，铠侠影响有限，暂时持有观察。"
    if soxx_pct >= 1:
        return "半导体温和上涨，对铠侠正面影响，持有为主。"
    return "市场无明显方向，铠侠维持震荡，正常持有。"

def nvda_outlook(nvda_pct):
    if nvda_pct <= -3:
        return f"英伟达大跌 {nvda_pct:.1f}%，AI芯片板块承压，注意止损。"
    if nvda_pct >= 3:
        return f"英伟达大涨 {nvda_pct:.1f}%，AI芯片需求强劲，持股受益。"
    if nvda_pct < 0:
        return f"英伟达小幅下跌 {nvda_pct:.1f}%，无重大影响，继续持有。"
    return f"英伟达上涨 {nvda_pct:.1f}%，走势良好，继续持有。"

def send_wechat(sendkey, title, body):
    data = urllib.parse.urlencode({"title": title, "desp": body}).encode()
    req = urllib.request.Request(f"https://sctapi.ftqq.com/{sendkey}.send", data=data)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def main():
    sendkey = os.environ["FTQQ_SENDKEY"]
    today   = datetime.date.today().strftime("%Y-%m-%d")
    now     = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime("%H:%M JST")

    print(f"[{today}] 半导体日报开始运行...")

    try:
        nvda = fetch_yahoo("NVDA")
        soxx = fetch_yahoo("SOXX")
    except Exception as e:
        print(f"数据获取失败: {e}")
        send_wechat(sendkey,
            f"⚠️ [半导体日报] 数据获取失败 {today}",
            f"请手动查看行情。\n错误: {e}")
        return

    nvda_pct = nvda["change_pct"]
    soxx_pct = soxx["change_pct"]

    level, level_word, advice = assess_level(soxx_pct, nvda_pct)

    nvda_sign = "+" if nvda_pct >= 0 else ""
    soxx_sign = "+" if soxx_pct >= 0 else ""

    title = f"{level} [半导体日报] 铠侠·英伟达 — {today}"
    body  = f"""**今日操作建议** · {now}

📌 铠侠(285A)：{"卖出/减仓" if soxx_pct <= -2 else "持有观察" if soxx_pct <= -1 else "持有"}
📌 英伟达(NVDA)：{"止损警惕" if nvda_pct <= -3 else "持有"}

> {advice}

---

**昨日美股收盘**

- SOXX 半导体ETF：{soxx_sign}{soxx_pct:.2f}%（${soxx['price']:.2f}）
- 英伟达(NVDA)：{nvda_sign}{nvda_pct:.2f}%（${nvda['price']:.2f}）

---

**铠侠(285A) 分析**

{kioxia_outlook(soxx_pct, nvda_pct)}

**英伟达(NVDA) 分析**

{nvda_outlook(nvda_pct)}

---

**判断依据**

市场等级：{level} {level_word}
- SOXX ≤ -2% 或 NVDA 涨跌 ≥ 3% → 🔴 重大
- SOXX 涨跌 1~2% 或 NVDA ≥ 1.5% → 🟡 注意
- 其他 → 🟢 稳定

---
GitHub Actions 云端自动运行 · {today} 08:00 JST"""

    result = send_wechat(sendkey, title, body)
    print(f"微信已发送: {result}")

if __name__ == "__main__":
    main()
