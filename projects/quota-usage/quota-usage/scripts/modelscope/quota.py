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
from datetime import date, datetime

CONFIG_PATH = os.environ.get(
    "MSC_CONFIG", "/var/minis/shared/msc-quota/config.json"
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


def collect(cfg: dict) -> dict:
    today = date.today().isoformat()
    bal = api_get("/openapi/v1/magicubes/balance", cfg)
    spend = api_get(
        "/openapi/v1/magicubes/transactions?type=SPEND_CONFIRM,EXPIRE&page=1&page_size=20",
        cfg,
    )
    earn = api_get(
        "/openapi/v1/magicubes/transactions?type=EARN&page=1&page_size=20", cfg
    )

    def agg(records, day=None):
        rows = [r for r in records if day is None or r.get("gmt_created") == day]
        return {
            "amount": sum(int(r.get("total_amount") or 0) for r in rows),
            "count": sum(int(r.get("count") or 0) for r in rows),
            "rows": rows,
        }

    return {
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "date": today,
        "balance": {
            "available": bal.get("available_balance"),
            "total": bal.get("total_balance"),
            "frozen": bal.get("frozen_amount"),
        },
        "spend_today": agg(spend.get("records", []), today),
        "spend_recent": [
            {k: r.get(k) for k in ("gmt_created", "total_amount", "count", "model_tier", "rule_key")}
            for r in spend.get("records", [])[:7]
        ],
        "earn_today": agg(earn.get("records", []), today),
    }


def estimate_cost(calls: int) -> dict:
    """按典型 agent 轮次（约 15k 输入，85% 缓存命中，0.5k 输出）估算。"""
    if not calls:
        return {"usd": 0.0, "cny": 0.0}
    inp = 15_000 * calls
    hit, miss = inp * 0.85, inp * 0.15
    usd = (
        hit / 1e6 * PRICE_HIT
        + miss / 1e6 * PRICE_MISS
        + (500 * calls) / 1e6 * PRICE_OUT
    )
    return {"usd": round(usd, 4), "cny": round(usd * USD_CNY, 4)}


def render(data: dict) -> str:
    b, s, e = data["balance"], data["spend_today"], data["earn_today"]
    lines = [
        f"魔粒余额（{data['checked_at']}）：可用 {b['available']} / 总额 {b['total']} / 冻结 {b['frozen']}",
        f"今日消耗：{s['amount']} 魔粒（{s['count']} 次调用）",
        f"今日发放：{e['amount']} 魔粒",
    ]
    if data.get("cost"):
        c = data["cost"]
        lines.append(
            f"今日等价 DeepSeek 官方费用：约 ¥{c['cny']:.2f}（${c['usd']:.3f}，低谷价）"
        )
    if data.get("spend_recent"):
        lines.append("近期消耗明细：")
        for r in data["spend_recent"]:
            lines.append(
                f"  {r['gmt_created']}  {r['total_amount']} 魔粒 / {r['count']} 次  [{r['model_tier']}] {r['rule_key']}"
            )
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