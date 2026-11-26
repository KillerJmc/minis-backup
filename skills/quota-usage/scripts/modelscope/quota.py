#!/usr/bin/env python3
"""魔搭（ModelScope）魔粒额度查询。

用法:
  python3 quota.py              # 人类可读输出
  python3 quota.py --json       # 机器可读 JSON（给 agent 用）
  python3 quota.py --cost       # 附带 DeepSeek 官方等价人民币成本估算

退出码:
  0  正常
  3  登录态失效（cookie 过期/被踢）——需要重新登录刷新 cookie
  4  配置缺失
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

CONFIG_PATH = os.environ.get(
    "MSC_CONFIG", "/var/minis/shared/quota/modelscope.json"
)
BASE = "https://modelscope.cn"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"
)
# DeepSeek 官方 deepseek-flash 低谷价（USD / 1M tokens）
PRICE_HIT, PRICE_MISS, PRICE_OUT = 0.003, 0.15, 0.60
USD_CNY = 7.10
MOLI_PER_CALL = 2  # 旗舰档：2 魔粒 / 次


def load_config() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(
            f"缺少配置文件 {CONFIG_PATH}，请先登录后执行 save_cookie.py",
            file=sys.stderr,
        )
        sys.exit(4)


def save_config(cfg: dict) -> None:
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, CONFIG_PATH)


def api_get(path: str, cfg: dict, timeout: int = 25) -> dict:
    req = urllib.request.Request(
        BASE + path,
        headers={
            "Cookie": f"m_session_id={cfg['m_session_id']}",
            "Accept": "application/json",
            "User-Agent": UA,
            "Referer": BASE + "/magicube/usage",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = json.loads(r.read().decode("utf-8", "replace"))
    if not body.get("success"):
        raise PermissionError(json.dumps(body, ensure_ascii=False)[:300])
    return body.get("data") or {}


def fmt_tokens(n) -> str:
    """1 亿以上用「亿」，1 万以上用「万」，其余原样（0 就显示 0）。与麦块云一致。"""
    n = int(n or 0)
    if n >= 100_000_000:
        return f"{n / 1e8:.2f} 亿"
    if n >= 10_000:
        return f"{n / 1e4:.2f} 万"
    return str(n)


def _all_records(cfg: dict, txn_type: str, cap: int = 20) -> list:
    """取完某类型全部流水（魔搭接口按页返回）。"""
    out, page = [], 1
    while page <= cap:
        d = api_get(
            f"/openapi/v1/magicubes/transactions?type={txn_type}&page={page}&page_size=100",
            cfg,
        ) or {}
        rows = d.get("records") or []
        out.extend(rows)
        total = int(d.get("total") or 0)
        if not rows or len(out) >= total:
            break
        page += 1
    return out


def collect(cfg: dict) -> dict:
    today = date.today()
    today_s = today.isoformat()
    win_start = (today - timedelta(days=2)).isoformat()   # 含今日共 3 天

    bal = api_get("/openapi/v1/magicubes/balance", cfg)
    spend_rows = _all_records(cfg, "SPEND_CONFIRM,EXPIRE")
    earn_rows = _all_records(cfg, "EARN")

    def amount(rows) -> int:
        return sum(int(r.get("total_amount") or 0) for r in rows)

    def pick(rows, start: str) -> list:
        return [r for r in rows if (r.get("gmt_created") or "") >= start]

    def cnt(rows) -> int:
        return sum(int(r.get("count") or 0) for r in rows)

    spend_only = [r for r in spend_rows if r.get("type") == "SPEND_CONFIRM"]
    expire_only = [r for r in spend_rows if r.get("type") == "EXPIRE"]

    spend_today = pick(spend_only, today_s)
    spend_win = pick(spend_only, win_start)
    earn_today = pick(earn_rows, today_s)

    # 签到 = 「每日发放」类规则今日是否已领取
    checked_in = None
    try:
        rules = api_get("/openapi/v1/magicubes/earn/rules", cfg) or []
        daily = [r for r in rules if r.get("category_key") == "daily"]
        if daily:
            checked_in = any(int(r.get("today_used") or 0) > 0 for r in daily)
    except Exception:  # noqa: BLE001
        checked_in = None

    return {
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "date": today_s,
        "balance": {
            "available": bal.get("available_balance"),
            "total": bal.get("total_balance"),
            "frozen": bal.get("frozen_amount"),
            "disabled": bool(bal.get("is_disabled")),
        },
        "overall": {
            # 总量与已用都排除「过期回收」，两者相加才闭合
            "earned": amount(earn_rows) - amount(expire_only),
            "spent": amount(spend_only),
        },
        "checkin": {"checked_in": checked_in},
        "spend_today": {"amount": amount(spend_today), "count": cnt(spend_today)},
        "spend_window": {"amount": amount(spend_win), "count": cnt(spend_win), "days": 3},
        "earn_today": {"amount": amount(earn_today), "count": cnt(earn_today)},
        "spend_recent": [
            {k: r.get(k) for k in ("gmt_created", "total_amount", "count", "model_tier", "rule_key")}
            for r in sorted(spend_rows, key=lambda r: r.get("gmt_created") or "", reverse=True)[:7]
        ],
    }


def render(d: dict) -> str:
    """与麦块云同构：标题 → 💰 额度（已用·剩余·总量 + 今日/近3天消耗）→ 💳 账户。"""
    b, o = d["balance"], d["overall"]
    st, sw, et, ck = d["spend_today"], d["spend_window"], d["earn_today"], d["checkin"]

    lines = [
        "魔搭额度",
        "",
        "💰 魔粒额度",
        "",
        f"- 已用 {fmt_tokens(o['spent'])}"
        f" · 剩余 {fmt_tokens(b['available'])}"
        f" · 总量 {fmt_tokens(o['earned'])}",
        f"- 今日消耗 {fmt_tokens(st['amount'])}"
        f" · 近 {sw['days']} 天消耗 {fmt_tokens(sw['amount'])}",
        "",
        "💳 账户",
        "",
    ]
    if ck.get("checked_in") is not None:
        lines.append(f"- 签到：{'是' if ck['checked_in'] else '否'}")
    lines.append(f"- 今日调用 {st['count']} 次 ｜ 近 {sw['days']} 天 {sw['count']} 次")
    if b.get("disabled"):
        lines.append("- ⚠️ 账户已被禁用")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="查询魔搭魔粒余额与消耗")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--cost", action="store_true", help="附带人民币成本估算")
    args = ap.parse_args()

    cfg = load_config()
    try:
        data = collect(cfg)
    except PermissionError as exc:
        print(f"AUTH_EXPIRED {exc}", file=sys.stderr)
        return 3
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            print(f"AUTH_EXPIRED HTTP {exc.code}", file=sys.stderr)
            return 3
        print(f"HTTP {exc.code}: {exc.reason}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"网络错误：{exc.reason}", file=sys.stderr)
        return 1

    if args.cost:
        data["cost"] = estimate_cost(data["spend_today"]["count"])

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(render(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())