#!/usr/bin/env python3
"""麦块云（Minekuai）额度查询 / 每日签到。

纯 HTTP，无需浏览器。token 存在 config.json，7 天有效。

用法:
  python3 quota.py            # 人读
  python3 quota.py --json     # 机器可读
  python3 checkin.py          # 每日签到（鱼币）

退出码:
  0  正常
  1  网络/接口错误
  2  接口返回业务错误（含额度未到账等需人工介入的情况）
  3  登录态失效 → 读 ../references/relogin.md
  4  配置缺失
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

BASE = "https://minekuai.cn"
CLIENT_ID = "428a8310cd442757ae699df5d894f051"  # 前端写死的 member 端 clientid
CONFIG_PATH = os.environ.get("MK_CONFIG", "/var/minis/shared/mk-quota/config.json")
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"
)


def load_config() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(
            f"缺少配置文件 {CONFIG_PATH}，请先登录后执行 login.py 或 save_token.py",
            file=sys.stderr,
        )
        sys.exit(4)


def save_config(cfg: dict) -> None:
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, CONFIG_PATH)


def _request(path: str, cfg: dict, method: str = "GET", body: dict | None = None,
             timeout: int = 25) -> dict:
    """发请求并返回解好的 JSON 包，不做 code 校验。"""
    data = json.dumps(body).encode() if body is not None else None
    headers = {
        "Authorization": f"Bearer {cfg['access_token']}",
        "clientid": cfg.get("client_id") or CLIENT_ID,
        "Accept": "application/json",
        "User-Agent": UA,
        "Origin": BASE,
        "Referer": BASE + "/",
    }
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def api(path: str, cfg: dict, method: str = "GET", body: dict | None = None,
        timeout: int = 25) -> dict:
    """调业务接口。path 形如 /app/balance（无 /api 前缀，站点根域）。

    返回 `{code, msg, data}` 里的 `data`；code 非 200 视为失败。
    """
    payload = _request(path, cfg, method, body, timeout)
    code = payload.get("code")
    if code == 401:
        raise PermissionError(payload.get("msg") or "token invalid")
    if code != 200:
        raise ValueError(f"[{code}] {payload.get('msg')}")
    return payload.get("data") or {}


def api_raw(path: str, cfg: dict, timeout: int = 30) -> dict:
    """调没有 `{code,msg,data}` 封装的接口（如 /app/llm/requests，正文就是 page 对象）。"""
    payload = _request(path, cfg, timeout=timeout)
    if payload.get("code") not in (None, 200):
        raise ValueError(f"[{payload.get('code')}] {payload.get('msg')}")
    return payload


def channel_usage(cfg: dict, days: int = 3, today_str: str | None = None) -> dict:
    """按 `groupCode` 聚合调用明细，给出各额度池「今日」与「近 N 天」的消耗。

    明细接口的分页参数是 **pageNum + pageSize**；传 page/current/offset 会被
    服务端静默忽略、永远返回第一页，所以这里只用 pageNum。

    失败不阻断主流程：返回各池为 0 且 `ok=False`，由调用方决定怎么展示。
    """
    today_str = today_str or datetime.now().strftime("%Y-%m-%d")
    try:
        start = datetime.strptime(today_str, "%Y-%m-%d")
    except ValueError:
        return {"ok": False}
    window = {(start - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)}

    today_k: dict[str, int] = defaultdict(int)
    span_k: dict[str, int] = defaultdict(int)
    ok = True
    page = 1
    while page <= 20:                      # 20 页 × 100 = 2000 条，够覆盖一个窗口
        try:
            page_obj = api_raw(f"/app/llm/requests?pageNum={page}&pageSize=100", cfg)
        except Exception:
            ok = False
            break
        rows = page_obj.get("rows") or []
        if not rows:
            break
        for row in rows:
            day = str(row.get("createTime") or "")[:10]
            if day not in window:
                continue
            used = sum(int(row.get(k) or 0) for k in
                       ("inputTokens", "cacheReadTokens", "outputTokens"))
            group = row.get("groupCode") or ""
            span_k[group] += used
            if day == today_str:
                today_k[group] += used
        total = int(page_obj.get("total") or 0)
        if total and page * 100 >= total:
            break
        page += 1

    def pick(prefix: str, source: dict) -> int:
        """同一个池可能落在多个 groupCode 上（如免费池的 default 与 lite_token）。"""
        return sum(v for k, v in source.items() if k.startswith(prefix))

    return {
        "ok": ok,
        "days": days,
        "paid_today": pick("paygo", today_k),
        "paid_window": pick("paygo", span_k),
        "today_pool_today": pick("default", today_k),
        "today_pool_window": pick("default", span_k),
        "perm_today": pick("lite_token", today_k),
        "perm_window": pick("lite_token", span_k),
    }


def collect(cfg: dict) -> dict:
    tok = api("/app/token", cfg)
    chk = api("/app/checkin", cfg)
    mem = api("/app/member/me", cfg)
    fish = api("/app/fish/mine", cfg)
    bal = api("/app/balance", cfg)

    today = tok.get("today") or {}
    perm = tok.get("permanent") or {}
    exch = tok.get("exchange") or {}
    paid = tok.get("paid") or {}
    buy = paid.get("buy") or {}
    usage = channel_usage(cfg, days=3)
    return {
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user": {"nickname": mem.get("nickname"), "phone": mem.get("phoneMasked"),
                 "group": fish.get("groupName"), "banned": bool(mem.get("apiBanned"))},
        "tokens": {
            "remaining": tok.get("remaining"),
            "today_total": (today.get("exchanged") or 0) + (today.get("bonus") or 0),
            "today_used": today.get("used"),
            "today_remaining": today.get("remaining"),
            "permanent_used": perm.get("totalUsed"),
            "permanent_remaining": perm.get("balance"),
            "permanent_total": perm.get("totalIn"),
            "permanent": perm.get("balance"),
            "mode": tok.get("mode"),
            "auto_exchange": tok.get("autoExchange"),
        },
        "cash": {"balance_yuan": float(bal.get("balance") or 0)},
        "coins": {"balance": float(fish.get("coins") or 0),
                  "per_hour": float(fish.get("coinsPerHour") or 0),
                  "max_hours": fish.get("maxHoursPerExchange")},
        "checkin": {
            "enabled": chk.get("enabled"),
            "checked_in": chk.get("checkedIn"),
            "awarded_today": float(chk.get("awardedToday") or 0),
            "base": float(chk.get("basePoints") or 0),
            "streak_days": chk.get("streakDays"),
            "next_bonus_in_days": chk.get("nextBonusInDays"),
            "streak_bonus": float(chk.get("streakBonus") or 0),
        },
        "exchange": {"open": exch.get("open"), "units_left": exch.get("unitsLeft"),
                     "daily_cap": exch.get("dailyCap"), "paused": exch.get("pausedMessage")},
        "usage": usage,
        "paid": {
            "group": paid.get("group"),
            "group_name": paid.get("groupName"),
            "balance": paid.get("balance"),
            "total_in": paid.get("totalIn"),
            "total_used": paid.get("totalUsed"),
            "keys": paid.get("keys"),
            "buy_open": buy.get("open"),
            "buy_paused": buy.get("pausedMessage"),
            "unit_yuan": buy.get("unitYuan"),
            "unit_tokens": buy.get("unitTokens"),
            "packs": [
                {"name": p.get("name"), "price_yuan": p.get("priceYuan"),
                 "total_tokens": p.get("totalTokens"), "left": p.get("left"),
                 "sold_out": p.get("soldOut"), "can_buy": p.get("canBuy")}
                for p in (paid.get("packs") or [])
            ],
        },
    }


def fmt_tokens(n) -> str:
    """1 亿以上用「亿」，1 万以上用「万」，其余原样（0 就显示 0）。"""
    n = int(n or 0)
    if n >= 100_000_000:
        return f"{n / 1e8:.2f} 亿"
    if n >= 10_000:
        return f"{n / 1e4:.2f} 万"
    return str(n)


def fmt_num(x) -> str:
    """整数不带小数，其余保留两位。用于鱼币这类小数值。"""
    v = float(x or 0)
    return str(int(v)) if v == int(v) else f"{v:.2f}"


def render(d: dict) -> str:
    """三区展示：付费额度 → 免费额度 → 账户。

    顺序刻意把付费放最前：2026-11-21 起免费不限量关闭，付费按量才是真实可用的额度。
    每个池都是「已用 · 剩余 · 总量」三槽位，两区排版一致，方便逐行对照。
    """
    t, c, usr = d["tokens"], d["checkin"], d["user"]
    paid = d.get("paid") or {}
    usage = d.get("usage") or {}
    days = usage.get("days") or 3

    lines = [
        f"麦块云额度 · {usr['nickname']}（{usr['phone']}）"
    ]

    # ── 付费额度
    if paid.get("balance") is not None:
        lines += [
            "",
            f"💰 付费额度（{paid.get('group_name') or '按量付费'}）",
            "",
            f"- 已用 {fmt_tokens(paid.get('total_used'))}"
            f" · 剩余 {fmt_tokens(paid.get('balance'))}"
            f" · 总量 {fmt_tokens(paid.get('total_in'))}",
        ]
        if usage:
            lines.append(
                f"- 今日消耗 {fmt_tokens(usage.get('paid_today'))}"
                f" · 近 {days} 天消耗 {fmt_tokens(usage.get('paid_window'))}"
            )

    # ── 免费额度：今日池单行，永久池带消耗子级
    lines += ["", "🎁 免费额度", ""]
    lines.append(
        f"- 今日 已用 {fmt_tokens(t.get('today_used'))}"
        f" · 剩余 {fmt_tokens(t.get('today_remaining'))}"
        f" · 总量 {fmt_tokens(t.get('today_total'))}"
    )
    lines.append(
        f"- 永久 已用 {fmt_tokens(t.get('permanent_used'))}"
        f" · 剩余 {fmt_tokens(t.get('permanent_remaining'))}"
        f" · 总量 {fmt_tokens(t.get('permanent_total'))}"
    )
    if usage:
        lines.append(
            f"  - 今日消耗 {fmt_tokens(usage.get('perm_today'))}"
            f" · 近 {days} 天消耗 {fmt_tokens(usage.get('perm_window'))}"
        )

    # ── 账户
    lines += ["", "💳 账户", ""]
    lines.append(f"- 鱼币 {fmt_num(d['coins']['balance'])}")
    lines.append(f"- 现金 ¥{d['cash']['balance_yuan']:.2f}")
    sign = "是" if c.get("checked_in") else "否"
    streak = c.get("streak_days")
    lines.append(f"- 签到：{sign}" + (f"（连签 {streak} 天）" if streak else ""))

    if usr.get("banned"):
        lines += ["", "⚠️ API 已被封禁"]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="查询麦块云额度")
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
