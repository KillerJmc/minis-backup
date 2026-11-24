#!/usr/bin/env python3
"""麦块云每日签到（纯 HTTP，领鱼币）。

签到给的是「鱼币」(coins)，10 鱼币 = 5000 万 token 的可兑换额度，
所以签到是维持 token 额度的前置动作。

用法:
  python3 checkin.py          # 人读
  python3 checkin.py --json   # 机器可读
  python3 checkin.py --status # 只看状态不签到

退出码:
  0  已签到 / 本次签到成功
  2  签到未成功（接口报错或开关关闭），需人工
  3  登录态失效 → 读 ../references/relogin.md
  4  配置缺失
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from quota import api, load_config, save_config
from exchange import do_exchange


def main() -> int:
    ap = argparse.ArgumentParser(description="麦块云每日签到（签到后自动兑换成 token）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--status", action="store_true", help="只看状态，不签到")
    ap.add_argument("--no-exchange", action="store_true",
                    help="跳过签到后的自动兑换（默认会兑换）")
    args = ap.parse_args()

    cfg = load_config()
    try:
        before = api("/app/checkin", cfg)
        did = False
        if not args.status and not before.get("checkedIn") and before.get("enabled"):
            api("/app/checkin", cfg, method="POST")
            did = True
        after = api("/app/checkin", cfg) if did else before
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

    result = {
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "did": did,
        "checked_in": after.get("checkedIn"),
        "awarded_today": float(after.get("awardedToday") or 0),
        "base": float(after.get("basePoints") or 0),
        "streak_days": after.get("streakDays"),
        "next_bonus_in_days": after.get("nextBonusInDays"),
        "streak_bonus": float(after.get("streakBonus") or 0),
        "cap_reached": after.get("capReached"),
        "balance": float(after.get("balance") or 0),
        "balance_cap": float(after.get("balanceCap") or 0),
    }

    cfg["last_checkin"] = {
        "at": result["checked_at"],
        "date": after.get("date"),
        "did": did,
        "awarded": result["awarded_today"],
    }
    try:
        save_config(cfg)
    except OSError:
        pass

    # 签到成功顺手把鱼币换成 token：auto 模式不是实时的，不转就会躺在账户里
    exch = None
    if not args.status and not args.no_exchange:
        exch = do_exchange(cfg, api)
    result["exchange"] = exch

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        head = "本次签到成功" if did else ("今日已签到" if result["checked_in"] else "未签到")
        print(f"麦块云签到（{result['checked_at']}）：{head}")
        if result["checked_in"]:
            print(f"  ✅ 今日获得 {result['awarded_today']:.0f} 鱼币（基础 {result['base']:.0f}）")
            print(f"  连续签到 {result['streak_days']} 天"
                  f"，再 {result['next_bonus_in_days']} 天额外 +{result['streak_bonus']:.0f}")
        if result["cap_reached"]:
            print(f"  ⚠️ 鱼币余额已达上限 {result['balance_cap']:.0f}")
        if exch:
            if exch.get("error"):
                print(f"  ⚠️ 自动兑换失败：{exch['error']}（可稍后手动 exchange.py）")
            elif exch["units"]:
                today = exch.get("today") or {}
                line = f"  💱 已兑换 {exch['units']} 单位 → {exch['tokens']/10000:.2f} 万 token"
                if today:
                    line += f"，今日剩余 {(today.get('remaining') or 0)/10000:.2f} 万"
                print(line)
            else:
                why = "兑换暂停" if exch.get("paused") else f"鱼币不足 10（当前 {exch['coins_before']:.2f}）"
                print(f"  · 未兑换：{why}")

    return 0 if result["checked_in"] else 2


if __name__ == "__main__":
    sys.exit(main())
