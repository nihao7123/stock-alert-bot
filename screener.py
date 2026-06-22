# -*- coding: utf-8 -*-
"""
潜力股雷达：扫半导体+电力股票池，找"近半年走出强趋势、且未过度透支"的标的
（找"下一个铠侠/キオクシア"的画像）。

设计：零第三方依赖（纯 urllib），直连 Yahoo Finance chart API，跑在 GitHub Actions。
模块映射用户要的"多 agent + 领导"：
  - 各板块独立算分（半导体组 / 电力组）
  - leader_rank() 统一打分、去重、剔除已透支、排序出 Top N
推送复用现有 Server酱 (FTQQ_SENDKEY)。
"""
import urllib.request
import urllib.parse
import json
import os
import sys
import time
import math
import datetime
from statistics import mean

from universe import UNIVERSE

# Windows 日文控制台(cp932)打印中文会崩，统一用 UTF-8（对 Linux/Actions 无副作用）
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ===================== 可调参数 =====================
MIN_RET_6M     = 15.0    # 近6月涨幅最低门槛(%)，低于此不算"走出趋势"
MIN_HISTORY    = 40      # 至少多少个交易日数据才分析
TOP_N          = 6       # 简报里列前几名
OVERHEAT_RSI   = 80.0    # RSI 超过此值视为过热
BLOWN_RET_6M   = 160.0   # 近6月涨幅超过此值 + 贴近高点 => "已起飞"，移出推荐
FETCH_DELAY    = 0.25    # 每次请求间隔(秒)，避免被限流
FETCH_RETRY    = 2       # 失败重试次数

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


# ===================== 数据获取 =====================
def fetch_chart(symbol):
    """取近1年日线。返回 (closes, volumes) 已剔除空值，按时间升序。失败返回 None。"""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?interval=1d&range=1y")
    last_err = None
    for attempt in range(FETCH_RETRY + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read())
            result = data["chart"]["result"][0]
            quote = result["indicators"]["quote"][0]
            raw_close = quote.get("close") or []
            raw_vol = quote.get("volume") or []
            closes, volumes = [], []
            for c, v in zip(raw_close, raw_vol):
                if c is not None:
                    closes.append(float(c))
                    volumes.append(float(v) if v is not None else 0.0)
            if len(closes) >= MIN_HISTORY:
                return closes, volumes
            return None
        except Exception as e:
            last_err = e
            time.sleep(0.6 * (attempt + 1))
    print(f"  [skip] {symbol}: {last_err}")
    return None


# ===================== 指标计算 =====================
def sma(values, n):
    if len(values) < n:
        return None
    return mean(values[-n:])


def rsi(closes, n=14):
    if len(closes) < n + 1:
        return None
    gains, losses = [], []
    for i in range(-n, 0):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_gain = mean(gains)
    avg_loss = mean(losses)
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def ret_pct(closes, days_ago):
    """相对 days_ago 个交易日前的涨幅(%)。不足则用最早值。"""
    if len(closes) <= 1:
        return 0.0
    idx = max(0, len(closes) - 1 - days_ago)
    base = closes[idx]
    if base == 0:
        return 0.0
    return (closes[-1] / base - 1.0) * 100.0


def crossed_ma200_recently(closes, lookback=120):
    """近 lookback 日内是否发生过'从200日均线下方突破到上方'——判断趋势是否近期才启动。"""
    if len(closes) < 200:
        # 历史不足200日的新股，若整体上行也视为近期趋势
        return ret_pct(closes, 60) > 10
    was_below = False
    start = max(200, len(closes) - lookback)
    for i in range(start, len(closes)):
        ma = mean(closes[i - 200:i])
        if closes[i] < ma:
            was_below = True
        elif was_below and closes[i] > ma:
            return True
    return False


def compute_metrics(closes, volumes):
    last = closes[-1]
    ma50 = sma(closes, 50)
    ma200 = sma(closes, 200)
    high_52w = max(closes[-252:]) if len(closes) >= 252 else max(closes)
    pct_from_high = (last / high_52w - 1.0) * 100.0 if high_52w else 0.0
    vol_recent = mean(volumes[-10:]) if len(volumes) >= 10 else 0.0
    vol_base = mean(volumes[-90:-10]) if len(volumes) >= 90 else (mean(volumes) if volumes else 0.0)
    vol_surge = (vol_recent / vol_base) if vol_base else 1.0
    return {
        "price": last,
        "ret_3m": ret_pct(closes, 63),
        "ret_6m": ret_pct(closes, 126),
        "ret_12m": ret_pct(closes, 252),
        "ma50": ma50,
        "ma200": ma200,
        "high_52w": high_52w,
        "pct_from_high": pct_from_high,
        "vol_surge": vol_surge,
        "rsi": rsi(closes),
        "recent_breakout": crossed_ma200_recently(closes),
    }


# ===================== 打分（leader 逻辑） =====================
def trend_alignment(m):
    p, ma50, ma200 = m["price"], m["ma50"], m["ma200"]
    if ma50 and ma200 and p > ma50 > ma200:
        return 100.0
    if ma200 and p > ma200:
        return 60.0
    if ma50 and p > ma50:
        return 40.0
    return 0.0


def proximity_score(pct_from_high):
    # 趋势完好(略低于高点)最理想；贴顶稍降；跌太多说明趋势已弱
    if -20 <= pct_from_high <= -2:
        return 100.0
    if pct_from_high > -2:
        return 75.0
    if -35 <= pct_from_high < -20:
        return 50.0
    return 25.0


def is_eligible(m):
    if m["ret_6m"] < MIN_RET_6M:
        return False
    if m["ma200"] and m["price"] < m["ma200"]:
        return False  # 跌破年线，谈不上上涨趋势
    return True


def is_blown_up(m):
    """已经暴涨且贴近高点/过热 —— 是'已经发生的铠侠'，移出推荐。"""
    if m["ret_6m"] >= BLOWN_RET_6M and m["pct_from_high"] > -8:
        return True
    if m["rsi"] is not None and m["rsi"] >= OVERHEAT_RSI and m["pct_from_high"] > -3:
        return True
    return False


def score(m):
    s = 0.0
    s += 0.30 * min(m["ret_6m"], 120.0) / 120.0 * 100.0
    s += 0.18 * min(max(m["ret_3m"], 0.0), 80.0) / 80.0 * 100.0
    s += 0.15 * min(m["vol_surge"], 3.0) / 3.0 * 100.0
    s += 0.15 * trend_alignment(m)
    s += 0.12 * proximity_score(m["pct_from_high"])
    s += 0.10 * (100.0 if m["recent_breakout"] else 0.0)
    # 过热轻度惩罚（不直接剔除，但降权）
    if m["rsi"] is not None and m["rsi"] >= OVERHEAT_RSI:
        s *= 0.7
    return s


def tags(m):
    t = []
    if m["recent_breakout"]:
        t.append("近期突破")
    if m["ma50"] and m["ma200"] and m["price"] > m["ma50"] > m["ma200"]:
        t.append("多头排列")
    if m["vol_surge"] >= 1.5:
        t.append(f"放量x{m['vol_surge']:.1f}")
    if m["pct_from_high"] > -3:
        t.append("逼近新高")
    if m["rsi"] is not None and m["rsi"] >= OVERHEAT_RSI:
        t.append(f"过热RSI{m['rsi']:.0f}")
    return "·".join(t) if t else "趋势向上"


# ===================== 主流程 =====================
def analyze_all():
    picks, blown, total = [], [], 0
    for symbol, (name, sector, market) in UNIVERSE.items():
        res = fetch_chart(symbol)
        time.sleep(FETCH_DELAY)
        if not res:
            continue
        closes, volumes = res
        total += 1
        m = compute_metrics(closes, volumes)
        m.update({"symbol": symbol, "name": name, "sector": sector, "market": market})
        if not is_eligible(m):
            continue
        m["score"] = score(m)
        if is_blown_up(m):
            blown.append(m)
        else:
            picks.append(m)
    picks.sort(key=lambda x: x["score"], reverse=True)
    blown.sort(key=lambda x: x["ret_6m"], reverse=True)
    return picks, blown, total


def fmt_row(rank, m):
    cur = "$" if m["market"] == "US" else "¥"
    code = m["symbol"].replace(".T", "")
    line = (f"**{rank}. {m['name']}（{code}）** {m['sector']}·{m['market']}\n"
            f"现价 {cur}{m['price']:.2f}｜近6月 **{m['ret_6m']:+.0f}%**｜近3月 {m['ret_3m']:+.0f}%"
            f"｜距52周高 {m['pct_from_high']:+.0f}%\n"
            f"信号：{tags(m)}\n")
    return line


def build_report(picks, blown, total, session):
    now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=9)
    date = now.strftime("%Y-%m-%d")
    hm = now.strftime("%H:%M JST")
    top = picks[:TOP_N]

    lines = [f"**潜力股雷达 · {session}** · {hm}",
             f"扫描 {total} 只半导体+电力股 → 命中趋势标的 {len(picks)} 只",
             ""]
    if top:
        lines.append(f"## 🎯 Top {len(top)}（近半年走强 × 未过度透支）\n")
        for i, m in enumerate(top, 1):
            lines.append(fmt_row(i, m))
    else:
        lines.append("今日股票池中无符合'强趋势且未透支'的标的。\n")

    if blown:
        names = "、".join(f"{b['name']}({b['ret_6m']:+.0f}%)" for b in blown[:6])
        lines.append("---")
        lines.append(f"## 🚫 已起飞·别追（涨幅过大/过热）\n{names}\n")

    lines.append("---")
    lines.append("⚠️ 量化自动筛选，数据来自 Yahoo Finance，可能延迟，**仅供研究，不构成投资建议**。下单前请用券商实时行情复核。")
    lines.append(f"GitHub Actions 云端运行 · {date}")
    return f"潜力股雷达 {date} · {session}", "\n".join(lines)


def send_wechat(sendkey, title, body):
    data = urllib.parse.urlencode({"title": title, "desp": body}).encode()
    req = urllib.request.Request(f"https://sctapi.ftqq.com/{sendkey}.send",
                                 data=data, headers=UA)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def main():
    session = os.environ.get("SESSION", "盘后扫描")
    sendkey = os.environ.get("FTQQ_SENDKEY", "").strip().lstrip("﻿")
    print(f"[{datetime.date.today()}] 潜力股雷达启动 · {session}")

    picks, blown, total = analyze_all()
    title, body = build_report(picks, blown, total, session)
    print(f"扫描 {total} 只，命中 {len(picks)} 只，已起飞 {len(blown)} 只")
    print("----- 报告预览 -----")
    print(body)

    if not sendkey:
        print("⚠️ 未设置 FTQQ_SENDKEY，跳过微信推送（仅打印）。")
        return
    try:
        result = send_wechat(sendkey, title, body)
        print(f"微信已发送: {result}")
    except Exception as e:
        print(f"微信推送失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
