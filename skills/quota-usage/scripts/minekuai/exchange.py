#!/usr/bin/env python3
"""麦块云（Minekuai）鱼币 → token 兑换。

10 鱼币 = 5000 万 token（1 个单位）。auto 模式不是实时触发，
所以签到后应立刻调用 do_exchange() 把鱼币换掉。

自用:
  python3 exchange.py            # 兑换所有可兑换单位
  python3 exchange.py --dry-run  # 只看当前可兑换单位
  python3 exchange.py --json     # 机器可读

被 checkin.py 引用:
  from exchange import do_exchange
  do_exchange(cfg, api, fish_mine)

退出码:
  0  已兑换 / 无可兑换单位
  2  接口业务错误
  3  登录态失效
  4  配置缺失
  1  网络错误
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))


def _load_quota():
    spec = importlib.util.spec_from_file_location("mk_quota", os.path.join(HERE, "quota.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def do_exchange(cfg: dict, api, fish_mine: dict | None = None) -> dict:
    """把可兑换单位全部换成 token。返回 {"units","tokens","coins_before","coins_after","today"}。

    不抛业务异常（兑换失败只记在返回的 error 字段），调用方决定如何展示。
    """
    out = {"units": 0, "tokens": 0, "coins_before": 0.0, "coins_after": 0.0,
           "today": None, "paused": None, "error": None}
    try:
        tok = api("/app/token", cfg)
        fish = fish_mine if fish_mine is not None else api("/app/fish/mine", cfg)
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"查询可兑换数量失败：{exc}"
        return out

    exch = tok.get("exchange") or {}
    out["units"] = int(exch.get("unitsLeft") or 0)
    out["paused"] = exch.get("paused")
    out["coins_before"] = float(fish.get("balance") or 0)
    out["coins_after"] = out["coins_before"]

    if out["units"] <= 0:
        return out

    total = 0
    done = 0
    for _ in range(out["units"]):
        try:
            r = api("/app/token/exchange", cfg, method="POST", body={})
        except Exception as exc:  # noqa: BLE001
            out["error"] = str(exc)
            break
        done += 1
        total += int(r.get("tokens") or 0)
        out["today"] = r.get("today")

    out["units"] = done
    out["tokens"] = total
    try:
        out["coins_after"] = float((api("/app/fish/mine", cfg) or {}).get("balance") or 0)
    except Exception:  # noqa: BLE001
        pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    q = _load_quota()
    cfg = q.load_config()
    try:
        tok = q.api("/app/token", cfg)
        fish = q.api("/app/fish/mine", cfg)
    except PermissionError:
        print("登录态失效，请执行 login.py 重新登录", file=sys.stderr)
        return 3
    except urllib.error.URLError as e:
        print(f"网络错误: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"业务错误: {e}", file=sys.stderr)
        return 2

    exch = tok.get("exchange") or {}
    units = int(exch.get("unitsLeft") or 0)
    coins = float(fish.get("balance") or 0)

    if args.dry_run or units <= 0:
        out = {"coins": coins, "units_left": units, "paused": exch.get("paused"),
               "exchanged": 0, "note": "dry-run" if args.dry_run else "无可兑换单位"}
        if args.json:
            print(json.dumps(out, ensure_ascii=False, indent=2))
        else:
            print(f"鱼币 {coins:.2f} ｜ 可兑换 {units} 单位"
                  + (f" ｜ 暂停: {exch.get('paused')}" if exch.get("paused") else "")
                  + ("" if units > 0 else "（鱼币不足 10，无法兑换）"))
        return 0

    res = do_exchange(cfg, q.api, fish)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        if res["units"]:
            today = res["today"] or {}
            print(f"兑换成功：{res['units']} 单位 → {res['tokens']/10000:.2f} 万 token")
            if today:
                limit = (today.get("exchanged") or 0) + (today.get("bonus") or 0)
                print(f"  今日剩余 {(today.get('remaining') or 0)/10000:.2f} 万 / 上限 {limit/10000:.2f} 万")
            print(f"  鱼币剩余 {res['coins_after']:.2f}")
        else:
            print(f"未兑换：{res['error'] or '没有可兑换单位'}")
    return 2 if res["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
