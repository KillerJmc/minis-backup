#!/usr/bin/env python3
"""魔搭（ModelScope）每日签到 / 魔粒状态自动检查。

纯 HTTP，无需浏览器：用配置文件里的 cookie 访问魔粒接口，
读取「每日发放」类规则的今日发放状态，必要时访问首页触发服务端每日登录判定。

用法:
  python3 checkin.py            # 人类可读
  python3 checkin.py --json     # 机器可读
  python3 checkin.py --force    # 即使今天已领取也再访问一次首页（幂等）

退出码:
  0  正常（已签到 / 本次签到成功）
  2  今日发放未到账，需要人工介入（多半是 cookie 失效或规则变了）
  3  登录态失效 —— 读 ../references/relogin.md
  4  配置缺失
  1  网络/接口错误
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from quota import BASE, CONFIG_PATH, api_get, load_config, save_config

DAILY_CATEGORY = "daily"
WARMUP_PATHS = ("/home",)  # 访问即会触发服务端「每日活跃」判定
WARMUP_DELAY = 6  # 秒：访问后等发放入账


def warmup(cfg: dict, timeout: int = 20) -> int:
    """访问首页触发每日登录发放，返回 HTTP 状态码。"""
    req = urllib.request.Request(
        BASE + WARMUP_PATHS[0],
        headers={
            "Cookie": f"m_session_id={cfg['m_session_id']}",
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"
            ),
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status


def daily_rules(cfg: dict) -> list[dict]:
    rules = api_get("/openapi/v1/magicubes/earn/rules", cfg)
    # api_get 已剥掉 data 层：正常是 list；个别版本返回 {"rules": [...]}
    if isinstance(rules, dict):
        rules = rules.get("rules") or rules.get("list") or []
    return [r for r in rules or [] if r.get("category_key") == DAILY_CATEGORY]


def collect(cfg: dict, retries: int = 3, delay: int = 4) -> dict:
    """先读状态；未到账则访问首页触发，再重读几轮。"""
    rules = daily_rules(cfg)
    warmup_status = None
    if any(int(r.get("today_remain") or 0) > 0 for r in rules):
        warmup_status = warmup(cfg)
        for i in range(retries):
            time.sleep(delay if i == 0 else delay)
            rules = daily_rules(cfg)
            if not any(int(r.get("today_remain") or 0) > 0 for r in rules):
                break

    bal = api_get("/openapi/v1/magicubes/balance", cfg)
    return {
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "date": date.today().isoformat(),
        "balance": {
            "available": bal.get("available_balance"),
            "total": bal.get("total_balance"),
            "frozen": bal.get("frozen_amount"),
        },
        "warmup_status": warmup_status,
        "daily": [
            {
                "key": r.get("rule_key"),
                "title": r.get("title"),
                "amount": int(r.get("amount") or 0),
                "expire_days": r.get("expire_days"),
                "today_used": int(r.get("today_used") or 0),
                "today_remain": int(r.get("today_remain") or 0),
                "today_earned_amount": int(r.get("today_earned_amount") or 0),
                "earned": int(r.get("today_used") or 0) > 0,
            }
            for r in rules
        ],
    }


def render(data: dict) -> str:
    b = data["balance"]
    d = data["daily"]
    got = sum(x["today_earned_amount"] for x in d)
    lines = [
        f"魔搭签到（{data['checked_at']}）：可用 {b['available']} 魔粒"
        f"（总额 {b['total']} / 冻结 {b['frozen']}）"
    ]
    for x in d:
        mark = "✅" if x["earned"] else "⏳"
        exp = f"，{x['expire_days']} 天有效" if x.get("expire_days") else ""
        lines.append(f"  {mark} {x['title']}：+{x['amount']} 魔粒{exp}")
    lines.append(f"今日合计发放：{got} 魔粒")
    pending = [x["title"] for x in d if not x["earned"]]
    if pending:
        lines.append(f"⚠️ 未到账：{', '.join(pending)} —— 可能需重新登录或人工处理")
    else:
        lines.append("✅ 今日签到完成")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="魔搭每日签到 / 魔粒状态检查")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--force", action="store_true", help="已领取也再触发一次首页（幂等）")
    ap.add_argument("--quiet", action="store_true", help="只在未完成时输出")
    args = ap.parse_args()

    cfg = load_config()
    try:
        if args.force:
            warmup(cfg)
            time.sleep(WARMUP_DELAY)
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

    # 记录最近一次签到结果，供 skill 判断是否需要重复执行
    cfg["last_checkin"] = {
        "at": data["checked_at"],
        "date": data["date"],
        "earned": sum(x["today_earned_amount"] for x in data["daily"]),
        "complete": all(x["earned"] for x in data["daily"]),
    }
    try:
        save_config(cfg)
    except OSError:
        pass

    done = all(x["earned"] for x in data["daily"])
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif not (args.quiet and done):
        print(render(data))
    return 0 if done else 2


if __name__ == "__main__":
    sys.exit(main())
