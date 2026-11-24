#!/usr/bin/env python3
"""七牛云登录态管理：保存 / 校验 PORTAL_SESSION。

七牛额度接口只需要一个 Cookie：`PORTAL_SESSION`（实测 SSID / PORTAL_UID 非必需）。

七牛 SSO 只有「账号密码」和「微信扫码」两种登录，没有短信，
也没有可编程的登录取 token 接口，所以**登录环节必须走浏览器**：

  1. 浏览器（或手机 App）登录 portal.qiniu.com
  2. get_cookies 导出 env 文件
  3. python3 login.py --from-env <env 文件>

之后的额度查询/检查全部是纯 HTTP，不再需要浏览器。

用法:
  python3 login.py --from-env /var/minis/offloads/env_cookies_qiniu_com_xxx.sh
  python3 login.py --value <PORTAL_SESSION>
  python3 login.py --check          # 校验当前配置

退出码:
  0  成功
  2  cookie 无效
  4  缺参数
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from quota import CONFIG_PATH, load_config, portal_get, save_config  # noqa: E402

CAMPAIGN = "1024-free"


def read_env_file(path: str) -> dict:
    out = {}
    text = open(path, "r", encoding="utf-8", errors="replace").read()
    for line in text.splitlines():
        m = re.match(r"^\s*(?:export\s+)?([A-Z0-9_]+)=['\"]?(.*?)['\"]?\s*$", line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def verify(cfg: dict) -> dict:
    return portal_get(
        f"/api/proxy/ai-inference/inapi/v1/free-model-campaigns/{CAMPAIGN}/quota", cfg
    )


def persist(session: str, extra: dict | None = None) -> int:
    cfg = {
        "portal_session": session,
        "campaign_id": CAMPAIGN,
        "user_model": "qiniu/conatus-free",
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if extra:
        for k in ("ssid", "portal_uid", "phone"):
            if extra.get(k):
                cfg[k] = extra[k]
    try:
        old = load_config()
        for k in ("ssid", "portal_uid", "phone"):
            if not cfg.get(k) and old.get(k):
                cfg[k] = old[k]
    except SystemExit:
        pass

    try:
        q = verify(cfg)
    except Exception as exc:  # noqa: BLE001
        print(f"❌ cookie 无效，未保存：{exc}", file=sys.stderr)
        return 2

    save_config(cfg)
    print(json.dumps({
        "saved_to": CONFIG_PATH,
        "remaining": q.get("remaining"),
        "limit": q.get("limit"),
        "reset_at": q.get("reset_at"),
    }, ensure_ascii=False))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="七牛登录态管理")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--from-env", metavar="FILE")
    src.add_argument("--value")
    src.add_argument("--check", action="store_true")
    ap.add_argument("--phone")
    args = ap.parse_args()

    if args.check:
        cfg = load_config()
        try:
            q = verify(cfg)
        except Exception as exc:  # noqa: BLE001
            print(f"❌ 登录态失效：{exc}", file=sys.stderr)
            return 2
        print(json.dumps({"ok": True, "remaining": q.get("remaining"),
                          "limit": q.get("limit")}, ensure_ascii=False))
        return 0

    if not (args.from_env or args.value):
        print("需要 --from-env / --value / --check 之一", file=sys.stderr)
        return 4

    extra = {"phone": args.phone} if args.phone else {}
    if args.from_env:
        env = read_env_file(args.from_env)
        session = env.get("COOKIE_PORTAL_SESSION", "")
        extra["ssid"] = env.get("COOKIE_SSID", "")
        extra["portal_uid"] = env.get("COOKIE_PORTAL_UID", "")
    else:
        session = (args.value or "").strip()

    if not session:
        print("PORTAL_SESSION 为空", file=sys.stderr)
        return 2
    return persist(session, extra)


if __name__ == "__main__":
    sys.exit(main())
