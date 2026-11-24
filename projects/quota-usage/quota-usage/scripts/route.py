#!/usr/bin/env python3
"""quota-usage 唯一入口：按当前会话的供应商路由到对应平台的额度/签到实现。

子命令：
    quota    查额度（默认）
    checkin  签到（麦块云含自动兑换）
    list     列出支持的平台与登录态状态

供应商识别链路（全部通过 minis-config 读取）：
    session.primaryModel     →  "group:<uuid>" | "entry:<providerUUID>/<model>"
    groups[<uuid>].entries[] →  entries[0] 是回退链主力
    providers[]              →  customBaseURL / label
平台判定只看 customBaseURL 域名（label 用户可改）。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PROVIDER_MAP = [
    ("minekuai.cn", "minekuai"),
    ("modelscope.cn", "modelscope"),
    ("qnaigc.com", "qiniu"),
    ("portal.qiniu.com", "qiniu"),
]

PLATFORMS = {
    "minekuai": {
        "name": "麦块云",
        "full": "Minekuai Cloud",
        "aliases": ["minekuai", "mk", "maikuai", "麦块", "麦块云"],
        "domains": ["minekuai.cn"],
        "login": "纯 HTTP（login.py --phone）",
        "site": "https://minekuai.cn",
        "console": "https://minekuai.cn/overview",
        "config": "/var/minis/shared/mk-quota/config.json",
        "dir": os.path.join(SKILL_ROOT, "scripts", "minekuai"),
    },
    "modelscope": {
        "name": "魔搭",
        "full": "ModelScope",
        "aliases": ["modelscope", "ms", "moda", "魔搭", "魔塔"],
        "domains": ["modelscope.cn", "api-inference.modelscope.cn"],
        "login": "需要浏览器（references/relogin.md）",
        "site": "https://modelscope.cn",
        "console": "https://modelscope.cn/magicube/usage",
        "config": "/var/minis/shared/msc-quota/config.json",
        "dir": os.path.join(SKILL_ROOT, "scripts", "modelscope"),
    },
    "qiniu": {
        "name": "七牛",
        "full": "Qiniu AI Inference",
        "aliases": ["qiniu", "qn", "七牛", "七牛云", "qnaigc", "conatus"],
        "domains": ["qnaigc.com", "portal.qiniu.com"],
        "login": "浏览器登 portal.qiniu.com 后 login.py --from-env",
        "site": "https://portal.qiniu.com",
        "console": "https://portal.qiniu.com/ai-inference/model?id=qiniu/conatus-free",
        "config": "/var/minis/shared/qiniu-quota/config.json",
        "dir": os.path.join(SKILL_ROOT, "scripts", "qiniu"),
    },
}

SUBCOMMANDS = ("quota", "checkin", "list")
USAGE = """用法：
  route.py quota    [--provider 平台|--all] [--json]   查额度（默认）
  route.py checkin  [--provider 平台|--all] [--json] [--no-exchange]
  route.py list     [--json]                           列出支持的平台"""


def run(args: list[str], timeout: int = 90,
        env: dict | None = None) -> tuple[int, str, str]:
    try:
        e = None
        if env:
            e = dict(os.environ)
            e.update(env)
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                           env=e)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 1, "", f"命令不存在：{args[0]}"
    except subprocess.TimeoutExpired:
        return 1, "", "执行超时"


def cfg_get(path: str):
    """读 minis-config 的某个路径，返回已解析的 value；失败返回 None。

    json/array 类字段的 value 是 JSON 字符串，做一次二次解包。
    """
    rc, out, _ = run(["minis-config", "get", path], timeout=30)
    if rc != 0 or not out.strip():
        return None
    try:
        val = json.loads(out).get("value")
    except (json.JSONDecodeError, AttributeError):
        return None
    if isinstance(val, str):
        try:
            val = json.loads(val)
        except json.JSONDecodeError:
            pass
    return val


def match_platform(text: str):
    """把用户给的平台名宽松匹配到平台标识。"""
    if not text:
        return None
    t = text.strip().lower()
    if t in PLATFORMS:
        return t
    for pid, meta in PLATFORMS.items():
        for a in meta["aliases"]:
            if t == a.lower() or a.lower() in t:
                return pid
    return None


def detect() -> dict:
    """返回当前会话绑定的 provider 信息与识别出的平台。"""
    info = {"provider_id": None, "label": None, "base_url": None,
            "model": None, "platform": None, "source": None}

    primary = cfg_get("session.primaryModel")
    if not primary:
        return info

    entry_ref = None
    if primary.startswith("entry:"):
        entry_ref, info["source"] = primary[6:], "entry"
    elif primary.startswith("group:"):
        gid = primary[6:]
        info["source"] = "group"
        groups = cfg_get("groups") or []
        matched = next((g for g in groups if g.get("id") == gid), None)
        if matched is None:
            # 绑定的组已被删除（例如重建过）：退回默认组
            info["source"] = "group(missing)"
            matched = next((g for g in groups if g.get("name") == "Default Models"), None)
        if matched:
            entries = matched.get("entries") or []
            if entries:
                e = entries[0]  # 回退链有多家供应商时，第一个是主力
                info["model"] = e.get("model_id")
                info["label"] = e.get("provider_label")
                info["provider_id"] = e.get("provider_id")
                entry_ref = e.get("entry_id")
    else:
        entry_ref, info["source"] = primary, "raw"

    if not info["provider_id"] and entry_ref and "/" in entry_ref:
        info["provider_id"] = entry_ref.split("/", 1)[0]
        info["model"] = info["model"] or entry_ref.split("/", 1)[1]

    for p in cfg_get("providers") or []:
        if p.get("id") == info["provider_id"]:
            info["label"] = info["label"] or p.get("label")
            info["base_url"] = p.get("customBaseURL")
            break

    url = ((info["base_url"] or "") + " " + (info["label"] or "")).lower()
    for host, key in PROVIDER_MAP:
        if host in url:
            info["platform"] = key
            break
    return info


def list_available(detected: dict, as_json: bool) -> int:
    rows = []
    for pid, meta in PLATFORMS.items():
        impl = meta["dir"]
        rows.append({
            "platform": pid,
            "name": meta["name"],
            "full": meta["full"],
            "aliases": meta["aliases"],
            "domains": meta["domains"],
            "site": meta.get("site"),
            "console": meta.get("console"),
            "login": meta["login"],
            "implemented": all(os.path.exists(os.path.join(impl, s))
                               for s in ("quota.py", "checkin.py")),
            "configured": os.path.exists(meta["config"]),
            "is_current": detected.get("platform") == pid,
        })

    if as_json:
        print(json.dumps({
            "ok": True,
            "current_provider": {
                "label": detected.get("label"),
                "base_url": detected.get("base_url"),
                "model": detected.get("model"),
                "platform": detected.get("platform"),
            },
            "platforms": rows,
        }, ensure_ascii=False, indent=2))
        return 0

    print(f"支持 {len(rows)} 个平台：")
    for r in rows:
        mark = "← 当前会话" if r["is_current"] else ""
        print(f"· {r['name']}（{r['platform']}，{r['full']}）{mark}")
        print(f"  别名：{' / '.join(r['aliases'])}")
        print(f"  域名：{', '.join(r['domains'])}")
        print(f"  官网：{r['site']} ｜ 控制台：{r['console']}")
        print(f"  登录：{r['login']}")
        state = ("已实现" if r["implemented"] else "未实现",
                 "已配置登录态" if r["configured"] else "未登录")
        print(f"  状态：{'，'.join(state)}")
    if detected.get("platform"):
        print(f"当前会话：{detected.get('label')}（{detected.get('base_url')}）"
              f" → {PLATFORMS[detected['platform']]['name']}")
    else:
        print("当前会话：未能识别（可用 --provider 指定）")
    return 0


def call_platform(platform: str, script: str, extra: list[str],
                  env: dict | None = None) -> tuple[int, str, str]:
    path = os.path.join(PLATFORMS[platform]["dir"], script)
    if not os.path.exists(path):
        return 1, "", f"未找到实现：{path}"
    return run([sys.executable, path, *extra], env=env)


def fail(msg: str, as_json: bool = False, code: int = 1) -> int:
    if as_json:
        print(json.dumps({"ok": False, "error": msg,
                          "available": list(PLATFORMS)}, ensure_ascii=False))
    else:
        print(f"❌ {msg}", file=sys.stderr)
        print("   可用：" + "、".join(
            f"{m['name']}({k})" for k, m in PLATFORMS.items()), file=sys.stderr)
    return code


def resolve_targets(args, detected: dict) -> tuple[list[str] | None, int]:
    """返回 (平台列表, 0) 或 (None, 非零退出码)。"""
    if getattr(args, "all", False):
        return list(PLATFORMS), 0
    if getattr(args, "provider", None):
        pid = match_platform(args.provider)
        if not pid:
            return None, fail(f"未知平台：{args.provider}", args.json)
        return [pid], 0
    if not detected["platform"]:
        if args.json:
            print(json.dumps({"ok": False, "error": "无法识别当前供应商",
                              "detected": detected,
                              "available": list(PLATFORMS)},
                             ensure_ascii=False, indent=2))
        else:
            print("❌ 无法识别当前供应商", file=sys.stderr)
            print(f"   当前绑定：{detected.get('source')} / "
                  f"{detected.get('label') or '未知'} / "
                  f"{detected.get('base_url') or '无 base URL'}", file=sys.stderr)
            print("   用 list 查看支持的平台，用 --provider <平台> 指定", file=sys.stderr)
        return None, 1
    return [detected["platform"]], 0


def cmd_query(args, detected: dict) -> int:
    targets, rc = resolve_targets(args, detected)
    if targets is None:
        return rc

    want_checkin = args.command == "checkin"
    script = "checkin.py" if want_checkin else "quota.py"
    extra = ["--json"] if args.json else []
    if want_checkin and args.no_exchange:
        extra.append("--no-exchange")

    results = []
    for pid in targets:
        out_rc, out, err = call_platform(pid, script, extra)
        results.append({"platform": pid, "name": PLATFORMS[pid]["name"],
                        "rc": out_rc, "out": out, "err": err})

    severity = [0, 1, 2, 4, 3]  # 3 最严重
    rc_out = 0
    for r in results:
        if r["rc"] in severity and severity.index(r["rc"]) > severity.index(rc_out):
            rc_out = r["rc"]

    if args.json:
        payload = {
            "ok": all(r["rc"] == 0 for r in results),
            "exit_code": rc_out,
            "mode": args.command,
            "provider": {"label": detected.get("label"),
                         "base_url": detected.get("base_url"),
                         "model": detected.get("model"),
                         "source": detected.get("source")},
            "platforms": [],
        }
        for r in results:
            item = {"platform": r["platform"], "platform_name": r["name"],
                    "exit_code": r["rc"], "result": None}
            try:
                item["result"] = json.loads(r["out"]) if r["out"].strip() else None
            except json.JSONDecodeError:
                item["raw"] = r["out"]
            if r["err"].strip():
                item["stderr"] = r["err"].strip()
            payload["platforms"].append(item)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return rc_out

    multi = len(results) > 1
    explicit = bool(getattr(args, "all", False) or getattr(args, "provider", None))
    for i, r in enumerate(results):
        if multi:
            if i:
                print()
            print(f"━━━ {r['name']}（{r['platform']}）━━━")
        elif not explicit:
            print(f"当前供应商：{detected.get('label') or '未知'}"
                  f"（{detected.get('base_url') or '—'}）· 平台 "
                  f"{PLATFORMS[r['platform']]['name']}")
            print("─" * 46)
        if r["out"].strip():
            print(r["out"].rstrip())
        if r["err"].strip():
            print(r["err"].rstrip(), file=sys.stderr)
        if r["rc"] != 0:
            hint = {2: "需人工介入", 3: "登录态失效，需要重新登录",
                    4: "缺少配置"}.get(r["rc"], "执行失败")
            print(f"⚠️ {r['name']}：{hint}", file=sys.stderr)
            if r["rc"] == 3:
                print(f"   登录方式：{PLATFORMS[r['platform']]['login']}",
                      file=sys.stderr)
    return rc_out


def build_parser(sub: str) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog=f"route.py {sub}", add_help=True)
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    if sub in ("quota", "checkin"):
        g = ap.add_mutually_exclusive_group()
        g.add_argument("--provider", metavar="平台", help="指定平台（支持别名）")
        g.add_argument("--all", action="store_true", help="对所有平台执行")
    if sub == "checkin":
        ap.add_argument("--no-exchange", action="store_true",
                        help="签到后不自动兑换鱼币（仅麦块云）")
    return ap


def main(argv: list[str]) -> int:
    sub = argv[0] if argv and not argv[0].startswith("-") else "quota"
    rest = argv[1:] if (argv and not argv[0].startswith("-")) else argv

    if sub in ("-h", "--help"):
        print(USAGE)
        return 0
    if sub not in SUBCOMMANDS:
        print(f"❌ 未知子命令：{sub}", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2

    args = build_parser(sub).parse_args(rest)
    args.command = sub

    detected = detect()
    if sub == "list":
        return list_available(detected, args.json)
    return cmd_query(args, detected)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))