#!/usr/bin/env python3
"""妙词元（api.miaotoken.cn / New API）额度查询。

鉴权模型（实测 2026-11-25）：
    账号密码 --登录--> refresh cookie（30 天）
    refresh cookie --刷新--> access token（15 分钟）
    access token + New-Api-User 头 --> 业务接口

所以磁盘上只存 refresh cookie，不存密码、不存 access token。

用法:
    python3 mt_quota.py            # 人读
    python3 mt_quota.py --json     # 机器可读

退出码:
    0 正常 ｜ 1 网络错误 ｜ 2 业务错误 ｜ 3 登录态失效（需重新 login）｜ 4 缺配置
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta

BASE = "https://api.miaotoken.cn"
CONFIG_PATH = os.environ.get("MT_CONFIG", "/var/minis/shared/mt-quota/config.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/18.0 Safari/605.1.15")


def load_config() -> dict:
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"缺少配置文件 {CONFIG_PATH}，请先登录", file=sys.stderr)
        sys.exit(4)
    except json.JSONDecodeError:
        print(f"配置文件损坏 {CONFIG_PATH}，请重新登录", file=sys.stderr)
        sys.exit(4)


def save_config(cfg: dict) -> None:
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, CONFIG_PATH)


def _req(path: str, method="GET", body=None, headers=None, timeout=25):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", UA)
    req.add_header("Origin", BASE)
    req.add_header("Referer", BASE + "/")
    if data:
        req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace")), (r.headers.get_all("Set-Cookie") or [])
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            body_json = json.loads(raw)
            code = body_json.get("code") or ""
            msg = body_json.get("message") or ""
        except json.JSONDecodeError:
            code, msg = "", raw[:120]
        if exc.code in (401, 403) or code.startswith("AUTH_"):
            raise PermissionError(f"{code or exc.code} {msg}".strip()) from None
        raise ValueError(f"HTTP {exc.code} {msg}".strip()) from None


def login(username: str, password: str) -> dict:
    """账号密码登录一次，落盘 refresh cookie 与 user_id。密码不保存。"""
    payload, cookies = _req("/api/user/login", "POST",
                            {"username": username, "password": password})
    if not payload.get("success"):
        raise PermissionError(payload.get("message") or "登录失败")
    refresh = ""
    for sc in cookies:
        if sc.startswith("new_api_refresh="):
            refresh = sc.split(";", 1)[0]
            break
    if not refresh:
        raise ValueError("登录成功但没拿到 new_api_refresh cookie")
    user = (payload.get("data") or {}).get("user") or {}
    cfg = {
        "refresh": refresh,
        "user_id": user.get("id"),
        "username": user.get("username"),
        "email": user.get("email"),
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_config(cfg)
    return cfg


def access_token(cfg: dict) -> str:
    """用 refresh cookie 换 access token；同时把轮换后的新 cookie 写回。"""
    payload, cookies = _req("/api/user/auth/refresh", "POST", {},
                            {"Cookie": cfg["refresh"], "Content-Type": "application/json"})
    if not payload.get("success"):
        raise PermissionError(payload.get("message") or "refresh 失败")
    for sc in cookies:
        if sc.startswith("new_api_refresh="):
            fresh = sc.split(";", 1)[0]
            if fresh != cfg["refresh"]:
                cfg["refresh"] = fresh
                save_config(cfg)
            break
    data = payload.get("data") or {}
    tok = data.get("access_token")
    if not tok:
        raise PermissionError("refresh 返回里没有 access_token")
    user = data.get("user") or {}
    if user.get("id") and user["id"] != cfg.get("user_id"):
        cfg["user_id"] = user["id"]
        save_config(cfg)
    return tok


class Api:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.token = access_token(cfg)

    def get(self, path: str):
        payload, _ = _req(path, headers={
            "Authorization": "Bearer " + self.token,
            "New-Api-User": str(self.cfg.get("user_id") or ""),
        })
        if payload.get("success") is False:
            msg = payload.get("message") or ""
            if "Unauthorized" in msg or "invalid access token" in msg:
                raise PermissionError(msg)
            raise ValueError(msg)
        return payload.get("data")

    def paged(self, path: str, per_page: int = 100, cap_pages: int = 60) -> list:
        """按 p 逐页取完，返回全部 item。

        坑（实测 2026-11-25）：`p` 是 1-based，p=0 与 p=1 都返回第 1 页。
        所以从 1 开始，并按 id 去重兜底。
        """
        seen: dict = {}
        total = None
        page = 1
        while page <= cap_pages:
            sep = "&" if "?" in path else "?"
            chunk = self.get(f"{path}{sep}p={page}&page_size={per_page}") or {}
            rows = chunk.get("items") or []
            if total is None:
                total = chunk.get("total") or 0
            for r in rows:
                rid = r.get("id")
                if rid is not None:
                    seen[rid] = r
            if not rows or len(rows) < per_page or (total is not None and len(seen) >= total):
                break
            page += 1
        return list(seen.values())


def collect(api: Api) -> dict:
    status = api.get("/api/status") or {}
    quota_per_unit = float(status.get("quota_per_unit") or 500000)
    price = float(status.get("price") or 1)
    usd = quota_per_unit * price          # 多少 quota = 1 美元

    me = api.get("/api/user/self") or {}
    tokens = api.get("/api/token/") or {}

    # 今日与近 3 天：按时间区间拉日志汇总（日志的 created_at 是秒级时间戳）
    now = datetime.now()
    today0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day0 = today0 - timedelta(days=2)
    start, end = int(day0.timestamp()), int(now.timestamp())
    logs = api.paged(f"/api/log/self?type=0&start_timestamp={start}&end_timestamp={end}", per_page=100)

    today_q = 0
    span_q = 0
    days: dict[str, int] = defaultdict(int)
    for row in logs:
        q = int(row.get("quota") or 0)
        if q <= 0:
            continue
        ts = int(row.get("created_at") or 0)
        day = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        days[day] += q
        span_q += q
        if day == today0.strftime("%Y-%m-%d"):
            today_q += q

    remain = int(me.get("quota") or 0)
    used = int(me.get("used_quota") or 0)
    items = tokens.get("items") or []
    return {
        "checked_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "user": {
            "username": me.get("username"),
            "display": me.get("display_name") or me.get("username"),
            "email": me.get("email"),
            "group": me.get("group"),
            "request_count": me.get("request_count"),
        },
        "quota": {
            "per_usd": usd,
            "used": used,
            "remain": remain,
            "total": used + remain,
            "used_usd": used / usd,
            "remain_usd": remain / usd,
            "total_usd": (used + remain) / usd,
        },
        "usage": {
            "today": today_q,
            "today_usd": today_q / usd,
            "span_days": 3,
            "span": span_q,
            "span_usd": span_q / usd,
            "by_day": {d: v / usd for d, v in sorted(days.items())},
        },
        "tokens": [{
            "name": t.get("name"),
            "unlimited": bool(t.get("unlimited_quota")),
            "remain": t.get("remain_quota"),
            "used": t.get("used_quota"),
            "expired": t.get("expired_time"),
        } for t in items],
        "tokens_count": tokens.get("total") or len(items),
    }


def fmt_usd(x) -> str:
    return f"{float(x or 0):.2f} 美元"


def render(d: dict) -> str:
    """与麦块云同构：标题 → 额度块（已用·剩余·总量 + 今日/近3天）→ 账户块。"""
    u, q, usg = d["user"], d["quota"], d["usage"]
    name = u.get("display") or u.get("username") or "—"
    who = name if not u.get("email") else f"{name}（{u['email']}）"

    lines = [f"妙词元额度 · {who}"]

    lines += ["", f"💰 额度（{u.get('group') or 'default'} 分组）", ""]
    lines.append(f"- 已用 {fmt_usd(q['used_usd'])} · 剩余 {fmt_usd(q['remain_usd'])}"
                 f" · 总量 {fmt_usd(q['total_usd'])}")
    lines.append(f"- 今日消耗 {fmt_usd(usg['today_usd'])}"
                 f" · 近 {usg['span_days']} 天消耗 {fmt_usd(usg['span_usd'])}")

    lines += ["", "💳 账户", ""]
    tk = d.get("tokens") or []
    if tk:
        t = tk[0]
        tag = "不限额度" if t.get("unlimited") else fmt_usd((t.get("remain") or 0) / q["per_usd"])
        extra = f"，共 {len(tk)} 个" if len(tk) > 1 else ""
        lines.append(f"- 令牌 {t.get('name') or '—'}（{tag}{extra}）")
    else:
        lines.append("- 令牌 0 个")
    lines.append(f"- 累计请求 {int(u.get('request_count') or 0)} 次")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="查询妙词元额度")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--login", nargs=2, metavar=("账号", "密码"),
                    help="登录并落盘 refresh cookie（密码不保存）")
    args = ap.parse_args()

    if args.login:
        try:
            cfg = login(*args.login)
        except PermissionError as exc:
            print(f"❌ 登录失败：{exc}", file=sys.stderr)
            return 3
        print(f"✅ 已保存登录态：{cfg.get('username')}（id {cfg.get('user_id')}）")
        return 0

    cfg = load_config()
    try:
        api = Api(cfg)
        data = collect(api)
    except PermissionError as exc:
        print(f"AUTH_EXPIRED {exc}", file=sys.stderr)
        print("   登录态失效，需要重新登录：--login <账号> <密码>", file=sys.stderr)
        return 3
    except ValueError as exc:
        print(f"API_ERROR {exc}", file=sys.stderr)
        return 2
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.reason}", file=sys.stderr)
        return 3 if exc.code in (401, 403) else 1
    except urllib.error.URLError as exc:
        print(f"网络错误：{exc.reason}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(render(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())