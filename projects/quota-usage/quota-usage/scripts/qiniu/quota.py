#!/usr/bin/env python3
"""七牛云 AI 推理（qnaigc）额度与消耗查询。

认证只需要一个 Cookie：`PORTAL_SESSION`。

数据来源：
  · 活动额度     free-model-campaigns/<id>/quota
  · 真实消耗     v3/stat/new（单位是 K token，需 ×1000）
  · API Key 汇总 v3/apikeys?with_quota=true（含 totalTokens）

注意：活动额度接口的 `used` 字段恒为 0（服务端未统计），
真实消耗必须走 stat/new，否则会显示「已用 0」的假象。

用法:
  python3 quota.py            # 人读
  python3 quota.py --json     # 机器可读

退出码:
  0  正常
  1  网络/接口错误
  2  接口返回业务错误
  3  登录态失效 → 读 ../references/relogin.md
  4  配置缺失
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime

PORTAL = "https://portal.qiniu.com"
API = "https://api.qnaigc.com"
CONFIG_PATH = os.environ.get("QN_CONFIG", "/var/minis/shared/qiniu-quota/config.json")
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"
)


def load_config() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"缺少配置文件 {CONFIG_PATH}，请先执行 login.py 导入 cookie", file=sys.stderr)
        sys.exit(4)


def save_config(cfg: dict) -> None:
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, CONFIG_PATH)


def portal_get(path: str, cfg: dict, timeout: int = 25) -> dict:
    req = urllib.request.Request(
        PORTAL + path,
        headers={
            "Cookie": f"PORTAL_SESSION={cfg['portal_session']}",
            "Accept": "application/json",
            "User-Agent": UA,
            "Referer": PORTAL + "/ai-inference",
            "Origin": PORTAL,
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = json.loads(r.read().decode("utf-8", "replace"))
    if body.get("code") == 401 or body.get("portalProxyCode") == 401:
        raise PermissionError(body.get("message") or "unauthorized")
    if not (body.get("status") is True or body.get("code") == 200):
        raise ValueError(body.get("message") or json.dumps(body, ensure_ascii=False)[:200])
    return body.get("data") or {}


def stat(cfg: dict, start: date, end: date, gran: str = "day") -> list[dict]:
    """拉用量统计。返回值已换算成 token（接口单位是 K token）。"""
    q = urllib.parse.urlencode({
        "api_key_id": "",
        "start": f"{start.isoformat()}T00:00:00+08:00",
        "end": f"{end.isoformat()}T23:59:59+08:00",
        "g": gran,
    })
    data = portal_get(f"/api/proxy/ai-inference/inapi/v3/stat/new?{q}", cfg)
    rows = []
    for m in data if isinstance(data, list) else []:
        item = {"model": m.get("name"), "input": 0, "cache": 0, "output": 0, "total": 0}
        for it in m.get("items") or []:
            v = float(it.get("total") or 0) * 1000  # K token → token
            key = it.get("key") or ""
            if key.startswith("cache"):
                item["cache"] += v
            elif key.startswith("ncache"):
                item["input"] += v
            elif key.startswith("output"):
                item["output"] += v
            item["total"] += v
        rows.append(item)
    return rows


def collect(cfg: dict) -> dict:
    cid = cfg.get("campaign_id") or "1024-free"
    quota = portal_get(f"/api/proxy/ai-inference/inapi/v1/free-model-campaigns/{cid}/quota", cfg)
    avail = portal_get(
        f"/api/proxy/ai-inference/inapi/v1/free-model-campaigns/{cid}/availability", cfg
    )
    user = portal_get("/api/gaea/user/overview", cfg)
    keys = portal_get("/api/proxy/ai-inference/inapi/v3/apikeys?with_quota=true", cfg)
    keys = keys if isinstance(keys, list) else []

    today = date.today()
    today_rows = stat(cfg, today, today)
    used_today = sum(r["total"] for r in today_rows)

    limit = int(quota.get("limit") or 0)
    # 活动额度接口的 used 不可信，用真实统计覆盖
    remaining = max(limit - int(used_today), 0) if limit else int(quota.get("remaining") or 0)


    return {
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user": {
            "name": user.get("full_name"),
            "mobile": user.get("mobile"),
            "balance_yuan": user.get("balance"),
        },
        "campaign": {
            "id": avail.get("campaign_id") or cid,
            "model": avail.get("user_model") or cfg.get("user_model"),
            "status": avail.get("status"),
            "callable": avail.get("callable"),
            "start_at": avail.get("start_at"),
            "end_at": avail.get("end_at"),
        },
        "quota": {
            "limit": limit,
            "used": int(used_today),
            "remaining": remaining,
            "reset_at": quota.get("reset_at"),
        },
        "today": {
            "input": sum(r["input"] for r in today_rows),
            "cache": sum(r["cache"] for r in today_rows),
            "output": sum(r["output"] for r in today_rows),
            "models": sorted(today_rows, key=lambda x: -x["total"])[:5],
        },
        "keys": [
            {"name": k.get("name"), "total_tokens": k.get("totalTokens"),
             "last_used": k.get("lastUsed"), "enabled": k.get("enabled")}
            for k in keys
        ],
    }


def fmt(n, unit: str = "token") -> str:
    n = float(n or 0)
    if unit == "token":
        if n >= 1e8:
            return f"{n / 1e8:.2f} 亿"
        if n >= 1e4:
            return f"{n / 1e4:.2f} 万"
        return f"{n:.0f}"
    return f"{n:.0f}"


def render(d: dict) -> str:
    q, c, u, t = d["quota"], d["campaign"], d["user"], d["today"]
    pct = (q["used"] / q["limit"] * 100) if q["limit"] else 0
    cache_rate = (t["cache"] / (t["cache"] + t["input"]) * 100) if (t["cache"] + t["input"]) else 0
    lines = [
        f"七牛额度（{d['checked_at']}）：{u.get('name')}（{u.get('mobile')}）",
        f"  今日剩余 {fmt(q['remaining'])} / 上限 {fmt(q['limit'])}"
        f"（已用 {fmt(q['used'])}，{pct:.2f}%）",
        f"  缓存输入 {fmt(t['cache'])} ｜ 非缓存输入 {fmt(t['input'])} ｜ 输出 {fmt(t['output'])}",
        f"  缓存命中率 {cache_rate:.1f}% ｜ 账户余额 ¥{u.get('balance_yuan')}",
        f"  模型 {c.get('model')} ｜ 活动 {c.get('id')}"
        f"（{str(c.get('start_at'))[:10]} ~ {str(c.get('end_at'))[:10]}）",
    ]
    if c.get("callable"):
        lines.append(f"  重置时间 {str(q.get('reset_at'))[:10]} ｜ ✅ 当前可调用")
    else:
        lines.append(f"  ⚠️ 当前不可调用（status={c.get('status')}）")

    if t["models"]:
        top = t["models"][0]
        lines.append(f"消耗最高 {top['model']}：{fmt(top['total'])} token")

    if d.get("keys"):
        k = d["keys"][0]
        total = k.get("total_tokens") or 0
        lines.append(f"Key {k.get('name')}（{k.get('last_used')}）：累计 {fmt(total)} token")

    if q["remaining"] == 0:
        lines.append("⚠️ 免费额度已用完，请求将被拒绝（需改用付费渠道）")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="查询七牛 AI 推理额度与消耗")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    try:
        data = collect(cfg)
    except PermissionError as exc:
        print(f"AUTH_EXPIRED {exc}", file=sys.stderr)
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
