#!/usr/bin/env python3
"""七牛云登录态管理：保存 / 校验 PORTAL_SESSION。

七牛额度接口只需要一个 Cookie：`PORTAL_SESSION`（实测 SSID / PORTAL_UID 非必需）。

登录是**纯 HTTP**，账号密码从环境变量 `QUOTA_QINIU_CRED` 读（格式「账号；密码」）。
流程与浏览器端一致：

  1. GET  web-api.qiniu.com/api/proxy/uc-biz/passport/public-key  取 RSA 公钥
  2. RSA/PKCS#1 v1.5 加密密码（纯 Python 实现，见 rsa.py）
  3. POST sso.qiniu.com/signin  {username, password, sign_in_type:1, captcha:""}
  4. 从响应 cookie 取 PORTAL_SESSION 落盘

密码只在本进程内存中出现，不打印、不落盘。

用法:
  python3 login.py                  # 用环境变量登录（推荐，无需任何网页操作）
  python3 login.py --from-env <env 文件>   # 已有浏览器 cookie 时直接落盘
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
import urllib.error
import urllib.request
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


SSO_BASE = "https://sso.qiniu.com"
PUBKEY_URL = "https://web-api.qiniu.com/api/proxy/uc-biz/passport/public-key"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/18.0 Safari/605.1.15")


# 公钥接口要求带 Referer/Origin，否则 403
_BROWSER_HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Referer": SSO_BASE + "/",
    "Origin": SSO_BASE,
}


def _json_get(url: str) -> dict:
    req = urllib.request.Request(url, headers=_BROWSER_HEADERS)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _lookup_user_id(phone: str) -> str:
    """手机号 → 内部 user_id。对应前端 GET /user-ids?phone_number=...。"""
    import urllib.parse
    url = f"{SSO_BASE}/user-ids?" + urllib.parse.urlencode({"phone_number": phone})
    payload = _json_get(url)
    ids = payload.get("user_ids") or []
    return str(ids[0].get("user_id")) if ids else ""


def web_login(account: str, password: str) -> str:
    """纯 HTTP 登录，返回 PORTAL_SESSION。密码不出本函数。"""
    import base64
    import rsa as qn_rsa

    pub = _json_get(PUBKEY_URL)
    pem = ((pub.get("data") or {}).get("public_key") or "").strip()
    if not pem:
        raise ValueError("取不到 RSA 公钥")
    enc = qn_rsa.encrypt_pkcs1v15(pem, password)

    # 邮箱直接用，手机号要先换成内部 user_id（前端 /user-ids 做的就是这个）
    if "@" in account:
        username, sign_in_type = account, 1
    else:
        uid = _lookup_user_id(account)
        if not uid:
            raise PermissionError("该手机号没有找到对应账号")
        username, sign_in_type = uid, 2

    body = json.dumps({
        "username": username,
        "password": enc,
        "sign_in_type": sign_in_type,
        "captcha": "",
    }).encode()
    req = urllib.request.Request(
        f"{SSO_BASE}/signin?client_id=&redirect_url=",
        data=body, method="POST",
        headers={**_BROWSER_HEADERS, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            payload = json.loads(r.read().decode("utf-8", "replace"))
            cookies = r.headers.get_all("Set-Cookie") or []
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            msg = json.loads(raw).get("message") or raw[:80]
        except json.JSONDecodeError:
            msg = raw[:80]
        raise PermissionError(f"登录失败 HTTP {exc.code}：{msg}") from None

    if payload.get("code") not in (0, 200, None) or payload.get("error"):
        raise PermissionError(f"登录被拒：{payload.get('message') or payload.get('error')}")

    for c in cookies:
        head = c.split(";", 1)[0]
        if head.startswith("PORTAL_SESSION="):
            return head.split("=", 1)[1]
    names = [c.split("=", 1)[0] for c in cookies]
    raise PermissionError(f"登录成功但没拿到 PORTAL_SESSION（收到 cookie: {names}）")


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
        for k in ():
            if extra.get(k):
                cfg[k] = extra[k]
    try:
        old = load_config()
        for k in ():
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
        # 默认走纯 HTTP 登录：账号密码从环境变量读
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import credentials  # noqa: E402
        try:
            account, password = credentials.load("qiniu", need_password=True)
        except credentials.CredentialError as exc:
            print(f"缺少凭证：{exc}", file=sys.stderr)
            return 4
        try:
            session = web_login(account, password)
        except PermissionError as exc:
            print(f"❌ {exc}", file=sys.stderr)
            return 2
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"网络错误：{exc}", file=sys.stderr)
            return 1
        return persist(session, {})

    extra = {}
    if args.from_env:
        env = read_env_file(args.from_env)
        session = env.get("COOKIE_PORTAL_SESSION", "")
    else:
        session = (args.value or "").strip()

    if not session:
        print("PORTAL_SESSION 为空", file=sys.stderr)
        return 2
    return persist(session, extra)


if __name__ == "__main__":
    sys.exit(main())
