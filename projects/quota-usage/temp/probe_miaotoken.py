#!/usr/bin/env python3
"""妙词元（api.miaotoken.cn / New API）用量探测。

设计原则：**密码只用一次**，登录成功后尝试生成系统访问令牌，之后存令牌不存密码。

用法:
    MT_USER=xxx MT_PASS=xxx python3 probe_miaotoken.py
    python3 probe_miaotoken.py --user xxx --pass xxx
    python3 probe_miaotoken.py --cookie "session=..."      # 已有登录态

只读：登录 + 若干 GET，原始响应落到 /tmp/mt_dump/。不写业务数据。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

BASE = "https://api.miaotoken.cn"
OUT = "/tmp/mt_dump"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/18.0 Safari/605.1.15")


class Client:
    def __init__(self):
        self.cookies: dict[str, str] = {}
        self.access_token: str | None = None
        self.headers: dict[str, str] = {}

    def _request(self, path, method="GET", body=None, extra=None):
        url = BASE + path
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", UA)
        req.add_header("Origin", BASE)
        req.add_header("Referer", BASE + "/")
        if data:
            req.add_header("Content-Type", "application/json")
        if self.cookies:
            req.add_header("Cookie", "; ".join(f"{k}={v}" for k, v in self.cookies.items()))
        for k, v in (extra or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                for sc in r.headers.get_all("Set-Cookie") or []:
                    k, _, rest = sc.partition("=")
                    self.cookies[k.strip()] = rest.split(";", 1)[0]
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")

    def login(self, username, password):
        return self._request("/api/user/login", "POST",
                             {"username": username, "password": password})

    def get(self, path, extra=None):
        return self._request(path, "GET", None, extra)


def save(name, text):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        f.write(text)


def brief(raw):
    try:
        o = json.loads(raw)
    except Exception:
        return "非 JSON: " + raw[:80]
    if not isinstance(o, dict):
        return type(o).__name__
    if o.get("success") is False:
        return "失败: " + str(o.get("message"))[:70]
    d = o.get("data", o)
    if isinstance(d, dict):
        return "keys: " + ", ".join(sorted(d)[:10])
    if isinstance(d, list):
        return f"list[{len(d)}]"
    return "ok"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default=os.environ.get("MT_USER"))
    ap.add_argument("--pass", dest="pwd", default=os.environ.get("MT_PASS"))
    ap.add_argument("--cookie")
    a = ap.parse_args()

    c = Client()
    if a.cookie:
        for kv in a.cookie.split(";"):
            if "=" in kv:
                k, v = kv.strip().split("=", 1)
                c.cookies[k] = v
        print("· 使用已有 cookie")
    else:
        if not (a.user and a.pwd):
            print("需要 --user/--pass（或环境变量 MT_USER/MT_PASS），或 --cookie")
            return 2
        st, raw = c.login(a.user, a.pwd)
        ok = False
        try:
            ok = bool(json.loads(raw).get("success"))
        except Exception:
            pass
        print(f"· 登录 HTTP {st} → {'成功' if ok else brief(raw)}")
        save("login.json", raw)
        if not ok:
            return 3
        print("  cookie: " + ", ".join(c.cookies)[:100])

    # 尝试生成系统访问令牌（有就用它，之后可以丢掉密码）
    st, raw = c.get("/api/user/token")
    save("access_token_probe.json", raw)
    print(f"· 访问令牌探测 HTTP {st} → {brief(raw)}")

    now = datetime.now()
    start = int((now - timedelta(days=7)).timestamp())
    end = int(now.timestamp())

    targets = [
        ("user_self.json", "/api/user/self"),
        ("tokens_p0.json", "/api/token/?p=0&size=100"),
        ("log_page1.json", "/api/log/self?p=0&page_size=20&type=0"),
        ("log_alt_params.json", "/api/log/self?page=1&page_size=20"),
        ("data_self_7d.json", f"/api/data/self?start_timestamp={start}&end_timestamp={end}&default_time=day"),
        ("status.json", "/api/status"),
    ]
    for name, path in targets:
        st, raw = c.get(path)
        save(name, raw)
        print(f"· {path}\n    HTTP {st} | {brief(raw)}")

    print(f"\n原始响应已存 {OUT}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())