#!/usr/bin/env python3
"""七牛云额度检查（七牛没有签到接口）。

七牛的免费模型是「活动每日额度」：qiniu/conatus-free → 活动 1024-free →
每天 1 亿 token，0 点由服务端自动重置。没有签到奖励，也不消耗用户操作。

所以这里的「签到」= 检查今日额度是否到账、活动是否有效、额度是否用完。

用法:
  python3 checkin.py
  python3 checkin.py --json

退出码:
  0  额度可用
  2  额度用完 / 活动失效，需人工（应切到付费渠道）
  3  登录态失效 → 读 ../references/relogin.md
  4  配置缺失
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from quota import load_config, portal_get, save_config, stat  # noqa: E402

CAMPAIGN = "1024-free"


def fmt(n) -> str:
    n = int(n or 0)
    if n >= 1e8:
        return f"{n / 1e8:.2f} 亿"
    if n >= 1e4:
        return f"{n / 1e4:.2f} 万"
    return str(n)


def main() -> int:
    ap = argparse.ArgumentParser(description="七牛 AI 推理额度检查")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    cid = cfg.get("campaign_id") or CAMPAIGN
    try:
        quota = portal_get(f"/api/proxy/ai-inference/inapi/v1/free-model-campaigns/{cid}/quota", cfg)
        avail = portal_get(
            f"/api/proxy/ai-inference/inapi/v1/free-model-campaigns/{cid}/availability", cfg
        )
        today = date.today()
        rows = stat(cfg, today, today)
        used_real = int(sum(r["total"] for r in rows))
    except PermissionError as exc:
        print(f"AUTH_EXPIRED {exc}", file=sys.stderr)
        return 3
    except ValueError as exc:
        print(f"API_ERROR {exc}", file=sys.stderr)
        return 2
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.reason}", file=sys.stderr)
        return 3 if exc.code in (401, 403) else 2
    except urllib.error.URLError as exc:
        print(f"网络错误：{exc.reason}", file=sys.stderr)
        return 2

    limit = int(quota.get("limit") or 0)
    # 活动接口的 used/remaining 不含真实消耗，用统计接口覆盖
    remaining = max(limit - used_real, 0) if limit else int(quota.get("remaining") or 0)
    result = {
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "campaign": cid,
        "status": avail.get("status"),
        "callable": avail.get("callable"),
        "eligible": avail.get("eligible"),
        "end_at": avail.get("end_at"),
        "limit": limit,
        "used": used_real,
        "remaining": remaining,
        "reset_at": quota.get("reset_at"),
        "ok": bool(avail.get("callable")) and remaining > 0,
    }

    cfg["last_checkin"] = {
        "at": result["checked_at"],
        "remaining": remaining,
        "callable": result["callable"],
    }
    try:
        save_config(cfg)
    except OSError:
        pass

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"七牛额度检查（{result['checked_at']}）")
        print(f"  活动 {cid}：{result['status']} ｜ 截止 {str(result['end_at'])[:10]}")
        print(f"  今日额度 {fmt(remaining)} / {fmt(result['limit'])}（已用 {fmt(result['used'])}）")
        print(f"  重置时间 {str(result['reset_at'])[:10]}")
        if result["ok"]:
            print("  ✅ 可正常调用（免费额度）")
        elif remaining <= 0:
            print("  ⚠️ 免费额度已用完，将回退到付费渠道")
        else:
            print(f"  ⚠️ 当前不可调用：status={result['status']} eligible={result['eligible']}")
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
