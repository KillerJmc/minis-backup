#!/usr/bin/env python3
"""妙词元（api.miaotoken.cn / New API）额度查询。

鉴权三段式（实测 2026-11-25）：
    账号密码 --登录--> refresh cookie（30 天）
    refresh cookie --刷新--> access token（15 分钟）
    access token + New-Api-User 头 --> 业务接口

磁盘只存 refresh cookie 与 user_id，不存密码、不存 access token。
refresh cookie 单次有效，每次刷新后立即原子写回。

用法:
    python3 quota.py                          # 人读
    python3 quota.py --json                   # 机器可读
    python3 quota.py --login <账号> <密码>     # 登录并落盘

退出码:
    0 正常 ｜ 1 网络/业务错误 ｜ 2 用法错误 ｜ 3 登录态失效 ｜ 4 缺配置 ｜ 5 限流
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

# 共享凭证模块在上一级目录（scripts/）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import credentials  # noqa: E402

BASE = "https://api.miaotoken.cn"
CONFIG_PATH = os.environ.get("MT_CONFIG", "/var/minis/shared/quota/miaotoken.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/18.0 Safari/605.1.15")
RETRY = 3


# ---------- 配置 ----------

def load_config() -> dict:
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"缺少配置文件 {CONFIG_PATH}，请先登录后执行 --login", file=sys.stderr)
        sys.exit(4)
    except json.JSONDecodeError:
        print(f"配置文件损坏 {CONFIG_PATH}，请重新 --login", file=sys.stderr)
        sys.exit(4)


def save_config(cfg: dict) -> None:
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, CONFIG_PATH)


# ---------- HTTP ----------

def _req(path: str, method="GET", body=None, headers=None, timeout=25):
    data = json.dumps(body).encode() if body is not None else None
    last = None
    for attempt in range(RETRY):
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
                return (json.loads(r.read().decode("utf-8", "replace")),
                        (r.headers.get_all("Set-Cookie") or []))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            try:
                bj = json.loads(raw)
                code, msg = bj.get("code") or "", bj.get("message") or ""
            except json.JSONDecodeError:
                code, msg = "", raw[:120]
            if exc.code == 429:
                wait = int(exc.headers.get("retry-after") or 0) or 90
                raise TimeoutError(f"HTTP 429 限流，{wait} 秒后可重试") from None
            if exc.code in (401, 403) or code.startswith("AUTH_"):
                raise PermissionError(f"{code or exc.code} {msg}".strip()) from None
            raise ValueError(f"HTTP {exc.code} {msg}".strip()) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
            if attempt + 1 < RETRY:
                time.sleep(2 * (attempt + 1))
    raise ValueError(f"网络错误：{last}")


# ---------- 鉴权 ----------

def login(username: str, password: str) -> dict:
    payload, cookies = _req("/api/user/login", "POST",
                            {"username": username, "password": password})
    if not payload.get("success"):
        raise PermissionError(payload.get("message") or "登录失败")
    refresh = next((c.split(";", 1)[0] for c in cookies
                    if c.startswith("new_api_refresh=")), "")
    if not refresh:
        raise ValueError("登录成功但没拿到 new_api_refresh cookie")
    user = (payload.get("data") or {}).get("user") or {}
    cfg = {
        "refresh": refresh,
        "user_id": user.get("id"),
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_config(cfg)
    return cfg


def access_token(cfg: dict) -> str:
    payload, cookies = _req("/api/user/auth/refresh", "POST", {},
                            {"Cookie": cfg["refresh"],
                             "Content-Type": "application/json"})
    if not payload.get("success"):
        raise PermissionError(payload.get("message") or "刷新失败")
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
        raise PermissionError("刷新返回里没有 access_token")
    uid = (data.get("user") or {}).get("id")
    if uid and uid != cfg.get("user_id"):
        cfg["user_id"] = uid
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

    def paged(self, path: str, per_page: int = 100, cap_pages: int = 80) -> list:
        """逐页取完返回全部 item。

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
            if not rows or len(rows) < per_page or len(seen) >= total:
                break
            page += 1
        return list(seen.values())


# ---------- 单价 ----------

def price_table(api: Api) -> dict:
    return {p.get("model_name"): p for p in (api.get("/api/pricing") or [])}


def input_price(table: dict, model: str, ratio: float) -> float | None:
    """返回该模型「未命中输入」的 ¥/百万 token。"""
    p = table.get(model) or {}
    expr = p.get("billing_expr")
    if expr:
        m = re.search(r'tier\("base",\s*p\s*\*\s*([\d.]+)', expr)
        if not m:
            return None
        return float(m.group(1)) * ratio
    mr = p.get("model_ratio")
    if mr:
        return float(mr) * ratio * 2
    return None


def baseline(rows: list, table: dict) -> dict | None:
    """基准模型 = 近 3 个「有数据」的日期里 token 用量最多的那一个。

    分组倍率取该模型最近一条日志里的 group_ratio（站点实际生效值）。
    """
    by_day: dict[str, dict[str, int]] = {}
    ratio_of: dict[str, float] = {}
    for r in rows:
        ts = int(r.get("created_at") or 0)
        if not ts:
            continue
        day = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        model = r.get("model_name") or "—"
        by_day.setdefault(day, {})
        by_day[day][model] = (by_day[day].get(model, 0)
                              + int(r.get("prompt_tokens") or 0)
                              + int(r.get("completion_tokens") or 0))
        try:
            ratio_of[model] = float(json.loads(r.get("other") or "{}").get("group_ratio"))
        except (ValueError, TypeError):
            pass
    days = sorted(by_day, reverse=True)[:3]
    if not days:
        return None
    agg: dict[str, int] = {}
    for d in days:
        for model, v in by_day[d].items():
            agg[model] = agg.get(model, 0) + v
    model = max(agg, key=agg.get)
    ratio = ratio_of.get(model)
    price = input_price(table, model, ratio) if ratio else None
    return {"model": model, "ratio": ratio, "price": price,
            "days": days, "tokens": agg[model]}


# ---------- 采集 ----------

def collect(api: Api) -> dict:
    status = api.get("/api/status") or {}
    qpu = float(status.get("quota_per_unit") or 500000)

    me = api.get("/api/user/self") or {}
    keys = api.get("/api/token/") or {}

    now = datetime.now()
    today0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    d3 = today0 - timedelta(days=2)
    rows = [r for r in api.paged("/api/log/self?type=2")
            if int(r.get("quota") or 0) > 0]

    hit = cache = out = today_tok = span_tok = 0
    for r in rows:
        c = int(json.loads(r.get("other") or "{}").get("cache_tokens") or 0)
        p = int(r.get("prompt_tokens") or 0)
        o = int(r.get("completion_tokens") or 0)
        hit += p - c
        cache += c
        out += o
        ts = int(r.get("created_at") or 0)
        if ts:
            dt = datetime.fromtimestamp(ts)
            if dt >= d3:
                span_tok += p + o
            if dt >= today0:
                today_tok += p + o

    table = price_table(api)
    base = baseline(rows, table)
    remain = int(me.get("quota") or 0)
    used_q = int(me.get("used_quota") or 0)
    remain_tok = (remain / qpu / base["price"] * 1_000_000
                  if base and base["price"] else None)

    return {
        "checked_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "user": {"display": me.get("display_name") or me.get("username"),
                 "request_count": me.get("request_count")},
        "cash": {"per_yuan": qpu, "remain": remain / qpu,
                 "used": used_q / qpu, "total": (remain + used_q) / qpu},
        "tokens": {"used": hit + cache + out, "hit": hit, "cache": cache,
                   "out": out, "today": today_tok, "span3": span_tok},
        "baseline": base,
        "remain_tokens": remain_tok,
        "keys": keys.get("total") or len(keys.get("items") or []),
    }


# ---------- 渲染 ----------

def fmt(n) -> str:
    """≥1 亿用亿、<1 亿用万、0 写 0。"""
    n = int(n or 0)
    if n == 0:
        return "0"
    return f"{n / 1e8:.2f} 亿" if n >= 1e8 else f"{n / 1e4:.2f} 万"


def render(d: dict) -> str:
    u, c, t, b = d["user"], d["cash"], d["tokens"], d["baseline"]
    who = u.get("display") or "—"

    lines = [f"妙词元额度 · {who}", "", "💰 额度", ""]
    line = f"- 已用 {fmt(t['used'])}"
    if d["remain_tokens"] is not None:
        line += f" · 剩余 {fmt(d['remain_tokens'])}（{b['model']} ¥{b['price']:g}/百万）"
    else:
        line += " · 剩余 —（无基准模型）"
    lines.append(line)
    lines.append(f"- 今日消耗 {fmt(t['today'])} · 近 3 天消耗 {fmt(t['span3'])}")
    lines += ["", "💳 账户", "", f"- 现金 ¥{c['remain']:.2f}"]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="妙词元额度查询")
    ap.add_argument("--login", nargs="?", const="", default=None, metavar="账号",
                    help="用环境变量 QUOTA_MIAOTOKEN_CRED 里的账号与密码登录；参数可省略")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        if args.login is not None:
            account = args.login
            try:
                env_account, password = credentials.load("miaotoken", need_password=True)
            except credentials.CredentialError as exc:
                print(f"缺少凭证：{exc}", file=sys.stderr)
                return 4
            if account and account != env_account:
                print("账号与环境变量里的不一致，以环境变量为准", file=sys.stderr)
            cfg = login(env_account, password)
            print(f"✅ 已保存登录态（id {cfg['user_id']}）")
            return 0
        data = collect(Api(load_config()))
        print(json.dumps(data, ensure_ascii=False, indent=2) if args.json
              else render(data))
        return 0
    except PermissionError as exc:
        print(f"AUTH {exc}", file=sys.stderr)
        print("   登录态失效，需要重新登录：--login（密码读 QUOTA_MIAOTOKEN_CRED）", file=sys.stderr)
        return 3
    except ValueError as exc:
        msg = str(exc)
        print(f"ERROR {msg}", file=sys.stderr)
        return 5 if "限流" in msg else 1


if __name__ == "__main__":
    sys.exit(main())