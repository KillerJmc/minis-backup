#!/usr/bin/env python3
"""把 modelScope 登录 cookie 写入配置文件（会先校验是否有效）。

用法:
  # 1) 从环境变量文件读取（推荐：get_cookies 生成的文件）
  python3 save_cookie.py --from-env /var/minis/offloads/env_cookies_modelscope_cn_xxx.sh

  # 2) 从标准输入读取裸 cookie 值
  echo "$VALUE" | python3 save_cookie.py --stdin

  # 3) 直接给值（不推荐，会留在命令历史里）
  python3 save_cookie.py --value <m_session_id>

可选 --phone 记录手机号，供下次自动发验证码使用。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from quota import CONFIG_PATH, api_get, load_config, save_config


def read_from_env_file(path: str) -> str:
    text = open(path, "r", encoding="utf-8", errors="replace").read()
    m = re.search(r"COOKIE_M_SESSION_ID=['\"]?([^'\"\n]+)", text)
    if not m:
        sys.exit(f"在 {path} 中没找到 COOKIE_M_SESSION_ID")
    return m.group(1).strip()


def all_cookies_from_env_file(path: str) -> dict:
    """把 get_cookies 生成的 env 文件解析成 {cookie_name: value}。

    env 变量名形如 COOKIE_SSXMOD_ITNA2，对应 cookie 名 ssxmod_itna2（全小写时无损）。
    """
    out = {}
    text = open(path, "r", encoding="utf-8", errors="replace").read()
    for line in text.splitlines():
        m = re.match(r"^\s*(?:export\s+)?COOKIE_([A-Z0-9_]+)=['\"]?(.*?)['\"]?\s*$", line)
        if m:
            out[m.group(1).lower()] = m.group(2)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--from-env", metavar="FILE")
    src.add_argument("--stdin", action="store_true")
    src.add_argument("--value")
    ap.add_argument("--phone", help="记录手机号（可选）")
    args = ap.parse_args()

    cookie = (
        read_from_env_file(args.from_env)
        if args.from_env
        else sys.stdin.read().strip()
        if args.stdin
        else (args.value or "").strip()
    )
    if not cookie:
        sys.exit("cookie 为空")

    cfg = {"m_session_id": cookie, "saved_at": None}
    try:
        old = load_config()
    except SystemExit:
        old = {}
    cfg["phone"] = args.phone or old.get("phone")
    if args.from_env:
        cfg["cookies"] = all_cookies_from_env_file(args.from_env)
        raw = open(args.from_env, encoding="utf-8", errors="replace").read()
        m = re.search(r"^\s*(?:export\s+)?BROWSER_COOKIE_HEADER=['\"]?(.*?)['\"]?\s*$", raw, re.M)
        if m:
            cfg["cookie_header"] = m.group(1)

    # 校验：余额接口能通才算有效
    try:
        bal = api_get("/openapi/v1/magicubes/balance", cfg)
    except Exception as exc:  # noqa: BLE001
        print(f"❌ cookie 无效，未保存：{exc}", file=sys.stderr)
        return 3

    from datetime import datetime

    cfg["saved_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_config(cfg)
    print(
        json.dumps(
            {
                "saved_to": CONFIG_PATH,
                "phone": cfg.get("phone"),
                "balance": bal.get("available_balance"),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())