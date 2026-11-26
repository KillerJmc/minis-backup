#!/usr/bin/env python3
"""麦块云全自动登录：手机号 → 发短信 → 用户给验证码 → 换 token → 落盘校验。

无需浏览器。依据：`POST /app/auth/sms/send` 没有任何风控签名，
带 clientid 头即可用 curl 直接发码（2026-11-16 实测）。

用法:
  # 一步到位（会交互式要验证码）
  python3 login.py --phone 1368xxxxxxx

  # 分两步：先发码，等用户给码再登录
  python3 login.py --phone 1368xxxxxxx --send-only
  python3 login.py --phone 1368xxxxxxx --code 123456

  # 已有 token（浏览器里复制的）直接落盘
  python3 login.py --token eyJhbGci...

退出码:
  0  成功
  2  登录失败（验证码错误/过期/发送过于频繁）
  4  缺参数
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import credentials  # noqa: E402
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from quota import BASE, CLIENT_ID, CONFIG_PATH, UA, api, load_config, save_config

LOGIN_URL = BASE + "/app/auth/login"
SMS_URL = BASE + "/app/auth/sms/send"


def _post(url: str, body: dict, token: str | None = None, timeout: int = 25) -> dict:
    headers = {
        "Content-Type": "application/json",
        "clientid": CLIENT_ID,
        "Accept": "application/json",
        "User-Agent": UA,
        "Origin": BASE,
        "Referer": BASE + "/login",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers=headers, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def send_sms(phone: str) -> dict:
    return _post(SMS_URL, {"phone": phone})


def login(phone: str, code: str) -> dict:
    """注意：验证码字段名是 smsCode，且必须带 grantType=sms。"""
    return _post(
        LOGIN_URL,
        {
            "phone": phone,
            "smsCode": code,
            "clientId": CLIENT_ID,
            "grantType": "sms",
        },
    )


def persist(token: str, phone: str | None, expire_in: int | None = None) -> int:
    cfg = {"access_token": token, "client_id": CLIENT_ID, "saved_at":
           datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    if expire_in:
        cfg["expire_in"] = expire_in

    try:
        tok = api("/app/token", cfg)
        mem = api("/app/member/me", cfg)
    except Exception as exc:  # noqa: BLE001
        print(f"❌ token 无效，未保存：{exc}", file=sys.stderr)
        return 2

    cfg["token_saved_date"] = datetime.now().strftime("%Y-%m-%d")
    save_config(cfg)
    remaining = tok.get("remaining")
    print(json.dumps({
        "saved_to": CONFIG_PATH,
        "user": mem.get("nickname"),
        "remaining_tokens": remaining,
    }, ensure_ascii=False))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="麦块云登录（纯 HTTP）")
    ap.add_argument("--phone", help="手机号；省略则读环境变量 QUOTA_MINEKUAI_CRED")
    ap.add_argument("--code")
    ap.add_argument("--token", help="已有 token 直接落盘")
    ap.add_argument("--send-only", action="store_true", help="只发验证码")
    args = ap.parse_args()

    if args.token:
        return persist(args.token.strip(), args.phone)

    phone = args.phone
    if not phone:
        try:
            phone, _ = credentials.load("minekuai")
        except credentials.CredentialError as exc:
            print(f"缺少凭证：{exc}", file=sys.stderr)
            return 4
        args.phone = phone

    if not args.code or args.send_only:
        try:
            r = send_sms(args.phone)
        except urllib.error.HTTPError as exc:
            print(f"HTTP {exc.code}: {exc.reason}", file=sys.stderr)
            return 2
        except urllib.error.URLError as exc:
            print(f"网络错误：{exc.reason}", file=sys.stderr)
            return 2
        if r.get("code") != 200:
            print(f"发码失败：[{r.get('code')}] {r.get('msg')}", file=sys.stderr)
            return 2
        print(f"✅ 验证码已发送到 {credentials.masked_account('minekuai') or '***'}（60 秒内只能发一次）")
        if args.send_only:
            return 0
        code = input("请输入 6 位验证码：").strip()
    else:
        code = args.code

    try:
        r = login(args.phone, code)
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.reason}", file=sys.stderr)
        return 2
    except urllib.error.URLError as exc:
        print(f"网络错误：{exc.reason}", file=sys.stderr)
        return 2

    if r.get("code") != 200:
        print(f"登录失败：[{r.get('code')}] {r.get('msg')}", file=sys.stderr)
        return 2

    data = r.get("data") or {}
    return persist(data.get("access_token"), args.phone, data.get("expire_in"))


if __name__ == "__main__":
    sys.exit(main())
