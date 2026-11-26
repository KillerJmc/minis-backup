#!/usr/bin/env python3
"""quota-usage 测试执行器。

用法:
    python3 tests/run.py            # 只跑离线用例
    python3 tests/run.py --live     # 含联网用例
    python3 tests/run.py -k list    # 只跑 id 含 list 的用例
    python3 tests/run.py --selftest # 负向自检：故意写错的用例必须被判失败

末行固定输出「共 N 项，失败 M 项」，M=0 才算通过（退出码 0）。
"""
from __future__ import annotations

import json
import os
import py_compile
import subprocess
import sys

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENTRY = os.path.join(SKILL_ROOT, "scripts", "route.py")
CASES = os.path.join(SKILL_ROOT, "tests", "cases.json")


def load_cases() -> list[dict]:
    with open(CASES, encoding="utf-8") as f:
        return json.load(f)["cases"]


def run_one(case: dict) -> tuple[bool, list[str]]:
    env = dict(os.environ)
    env.update(case.get("env") or {})
    try:
        p = subprocess.run([sys.executable, ENTRY, *case["argv"]],
                           capture_output=True, text=True, timeout=120, env=env)
        rc, out, err = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return False, ["执行超时"]

    problems = []
    if rc != case["expect_rc"]:
        problems.append(f"退出码 {rc}，期望 {case['expect_rc']}")
    for s in case.get("stdout_has") or []:
        if s not in out:
            problems.append(f"stdout 缺少 {s!r}")
    for s in case.get("stderr_has") or []:
        if s not in err:
            problems.append(f"stderr 缺少 {s!r}")
    for s in case.get("stdout_not_has") or []:
        if s in out:
            problems.append(f"stdout 不应出现 {s!r}")

    if case.get("idempotent"):
        again = subprocess.run([sys.executable, ENTRY, *case["argv"]],
                               capture_output=True, text=True, timeout=120, env=env)
        if again.stdout != out or again.returncode != rc:
            problems.append("连跑两次结果不一致")
    return not problems, problems


def check_static() -> tuple[bool, list[str]]:
    """入口与所有平台脚本必须能编译（语法检查）。"""
    problems = []
    for root, _, files in os.walk(SKILL_ROOT):
        if "__pycache__" in root:
            continue
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(root, fn)
            try:
                py_compile.compile(path, doraise=True)
            except py_compile.PyCompileError as exc:
                problems.append(f"{os.path.relpath(path, SKILL_ROOT)}: {exc.msg}")
    return not problems, problems


def check_render() -> tuple[bool, list[str]]:
    """用构造数据渲染麦块云额度，断言三区结构与槽位顺序。不联网。"""
    import importlib.util

    path = os.path.join(SKILL_ROOT, "scripts", "minekuai", "quota.py")
    spec = importlib.util.spec_from_file_location("mk_quota_render", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    sample = {
        "checked_at": "2026-11-24 00:00:00",
        "user": {"nickname": "N", "group": "Lite", "banned": False},
        "tokens": {"today_used": 0, "today_remaining": 0, "today_total": 0,
                   "permanent_used": 15241069, "permanent_remaining": 54758931,
                   "permanent_total": 70000000},
        "cash": {"balance_yuan": 0.0},
        "coins": {"balance": 10.0},
        "checkin": {"checked_in": True, "streak_days": 1},
        "paid": {"balance": 1173074866, "total_in": 1200000000,
                 "total_used": 26925134, "group_name": "按量付费"},
        "usage": {"ok": True, "days": 3, "paid_today": 7662000,
                  "paid_window": 10976300, "today_pool_today": 0,
                  "perm_today": 0, "perm_window": 0},
    }
    out = mod.render(sample)

    problems = []
    for block in ("💰 付费额度", "🎁 免费额度", "💳 账户"):
        if block not in out:
            problems.append(f"缺区块 {block}")
    # 三区顺序必须是 付费 → 免费 → 账户
    order = [out.find(b) for b in ("💰 付费额度", "🎁 免费额度", "💳 账户")]
    if order != sorted(order):
        problems.append("区块顺序不是 付费 → 免费 → 账户")
    # 槽位顺序：已用 · 剩余 · 总量（取第一处出现的位置）
    slots = [out.find("已用"), out.find("剩余"), out.find("总量")]
    if slots != sorted(slots) or -1 in slots:
        problems.append("槽位顺序不是「已用 · 剩余 · 总量」")
    for needle in ("今日消耗", "近 3 天消耗", "签到：是", "鱼币 10"):
        if needle not in out:
            problems.append(f"缺 {needle}")
    if "（" in out.splitlines()[0] and "额度" in out.splitlines()[0]:
        problems.append("首行不该再带括号里的账号")
    if "亿" not in out:
        problems.append("超过 1 亿未切到亿单位")
    return not problems, problems


def check_render_miaotoken() -> tuple[bool, list[str]]:
    """用构造数据渲染妙词元额度，断言两区结构、单位切换与口径标注。不联网。"""
    import importlib.util

    path = os.path.join(SKILL_ROOT, "scripts", "miaotoken", "quota.py")
    spec = importlib.util.spec_from_file_location("mt_quota_render", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    sample = {
        "checked_at": "2026-11-26 15:00:00",
        "user": {"display": "K", "request_count": 1789},
        "cash": {"per_yuan": 500000.0, "remain": 3.6375, "used": 26.36,
                 "total": 30.0},
        "tokens": {"used": 188746684, "hit": 43096816, "cache": 144706587,
                   "out": 943281, "today": 0, "span3": 757474},
        "baseline": {"model": "gpt-6.1-sol", "ratio": 0.1, "price": 0.2,
                     "days": ["2026-11-24"], "tokens": 1},
        "remain_tokens": 18187300.0,
        "keys": 1,
    }
    out = mod.render(sample)

    problems = []
    for block in ("💰 额度", "💳 账户"):
        if block not in out:
            problems.append(f"缺区块 {block}")
    if "🎁" in out:
        problems.append("妙词元只有一个额度池，不该出现免费额度区")
    slots = [out.find("已用"), out.find("剩余")]
    if slots != sorted(slots) or -1 in slots:
        problems.append("槽位顺序不是「已用 · 剩余」")
    if "总量" in out:
        problems.append("已用为实测、剩余为折算，口径不同，不该输出总量")
    for needle in ("今日消耗", "近 3 天消耗", "gpt-6.1-sol", "¥0.2/百万",
                   "现金 ¥3.64"):
        if needle not in out:
            problems.append(f"缺 {needle}")
    # 1.89 亿 / 1818.73 万 / 0 → 三种单位各出现一次
    if "1.89 亿" not in out:
        problems.append("已用未按「亿」显示")
    if "1818.73 万" not in out:
        problems.append("剩余未按「万」显示")
    if "今日消耗 0 ·" not in out:
        problems.append("0 值未简写为 0")
    if "@" in out:
        problems.append("输出里出现了邮箱，账号信息不应展示")
    return not problems, problems


def check_credentials() -> tuple[bool, list[str]]:
    """账号口令解析：三种分隔符、无分隔符、密码内含分号、缺变量。不联网。"""
    import importlib.util

    path = os.path.join(SKILL_ROOT, "scripts", "credentials.py")
    spec = importlib.util.spec_from_file_location("cred_mod", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    problems = []
    cases = [
        ("user@example.com；pass", ("user@example.com", "pass")),
        ("user@example.com;pass", ("user@example.com", "pass")),
        ("user@example.com pass", ("user@example.com", "pass")),
        ("13800000000", ("13800000000", "")),
        ("  a@b.c；p；q  ", ("a@b.c", "p；q")),
        ("", ("", "")),
    ]
    for raw, want in cases:
        got = mod.parse(raw)
        if got != want:
            problems.append(f"{raw!r} 解析成 {got}，应为 {want}")

    # 缺变量时抛 CredentialError
    saved = {k: os.environ.pop(k, None) for k in list(mod.VAR_MAP.values())}
    try:
        mod.load("miaotoken", need_password=True)
        problems.append("缺变量时没报错")
    except mod.CredentialError:
        pass
    # 有账号无密码时也要报错（密码类平台）
    os.environ["QUOTA_MINEKUAI_CRED"] = "13800000000"
    os.environ["QUOTA_MIAOTOKEN_CRED"] = "user@example.com"
    try:
        mod.load("miaotoken", need_password=True)
        problems.append("缺密码段时没报错")
    except mod.CredentialError:
        pass
    # 短信类平台只填账号即可
    try:
        acc, pwd = mod.load("minekuai")
        if acc != "13800000000" or pwd:
            problems.append("短信类平台解析结果不对")
    except mod.CredentialError as exc:
        problems.append(f"短信类平台不该报错：{exc}")
    # 显示打码
    masked = mod.masked_account("minekuai")
    if "@" in masked or "example" in masked:
        problems.append(f"打码结果泄漏内容：{masked}")

    for k, v in saved.items():
        os.environ.pop(k, None)
        if v is not None:
            os.environ[k] = v
    return not problems, problems


def check_render_platform(name: str, mod_path: str, sample: dict,
                          must: list[str], must_not: list[str]) -> tuple[bool, list[str]]:
    """通用渲染断言：给定构造数据，检查必含与必不含的片段。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location(f"render_{name}", mod_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = mod.render(sample)
    problems = [f"缺 {x}" for x in must if x not in out]
    problems += [f"不该出现 {x}" for x in must_not if x in out]
    if "💰" not in out or "💳 账户" not in out:
        problems.append("缺少 额度区 或 账户区")
    return not problems, problems


def report(name: str, ok: bool, problems: list[str]) -> None:
    print(f"{'✅' if ok else '❌'} {name}")
    for p in problems:
        print(f"   ↳ {p}")


def main(argv: list[str]) -> int:
    live = "--live" in argv
    selftest = "--selftest" in argv
    keyword = None
    if "-k" in argv:
        i = argv.index("-k")
        if i + 1 < len(argv):
            keyword = argv[i + 1]

    total = failed = 0

    total += 1
    ok, problems = check_static()
    report("static: py_compile", ok, problems)
    if not ok:
        failed += 1

    total += 1
    ok, problems = check_render()
    report("render: 三区结构与槽位顺序", ok, problems)
    if not ok:
        failed += 1

    total += 1
    ok, problems = check_credentials()
    report("credentials: 分隔符解析与缺变量提示", ok, problems)
    if not ok:
        failed += 1

    total += 1
    ok, problems = check_render_platform(
        "modelscope", os.path.join(SKILL_ROOT, "scripts", "modelscope", "quota.py"),
        {
            "checked_at": "2026-11-26 18:00:00", "date": "2026-11-26",
            "balance": {"available": 0, "total": 0, "frozen": 0, "disabled": False},
            "overall": {"earned": 446, "spent": 446},
            "checkin": {"checked_in": False},
            "spend_today": {"amount": 0, "count": 0},
            "spend_window": {"amount": 0, "count": 0, "days": 3},
            "earn_today": {"amount": 0, "count": 0},
        },
        must=["魔搭额度", "💰 魔粒额度", "已用 446", "剩余 0", "总量 446",
              "今日消耗", "近 3 天消耗", "签到：否", "今日调用"],
        must_not=["过期", "冻结", "发放"],
    )
    report("render: 魔搭结构与口径", ok, problems)
    if not ok:
        failed += 1

    total += 1
    ok, problems = check_render_platform(
        "qiniu", os.path.join(SKILL_ROOT, "scripts", "qiniu", "quota.py"),
        {
            "checked_at": "2026-11-26 18:00:00",
            "user": {"balance_yuan": 0},
            "campaign": {"id": "1024-free", "model": "qiniu/conatus-free",
                         "status": "active", "callable": True,
                         "start_at": "2026-10-24T00:00:00+08:00",
                         "end_at": "2026-12-30T23:59:59+08:00"},
            "quota": {"limit": 100000000, "used": 0, "remaining": 100000000,
                      "reset_at": "2026-11-27T00:00:00+08:00"},
            "today": {"cache": 0, "input": 0, "output": 0, "total": 0, "models": []},
            "window": {"days": 3, "total": 0},
            "keys": [],
        },
        must=["七牛额度", "💰 额度", "剩余 1.00 亿", "总量 1.00 亿",
              "今日消耗", "近 3 天消耗", "到期 2026-12-30", "余额 ¥0"],
        must_not=["签到", "模型 qiniu", "重置", "Key"],
    )
    report("render: 七牛结构与字段裁剪", ok, problems)
    if not ok:
        failed += 1

    total += 1
    ok, problems = check_render_miaotoken()
    report("render: 妙词元两区与口径标注", ok, problems)
    if not ok:
        failed += 1

    cases = load_cases()
    if keyword:
        cases = [c for c in cases if keyword in c["id"]]
    skipped = 0
    for case in cases:
        if case.get("network") and not live:
            skipped += 1
            continue
        total += 1
        ok, problems = run_one(case)
        report(f"{case['id']}（{case['user']}）", ok, problems)
        if not ok:
            failed += 1

    if skipped:
        print(f"⏭ 跳过 {skipped} 项联网用例（加 --live 运行）")

    if selftest:
        total += 1
        bad = {"id": "selftest", "user": "故意写错的期望", "argv": ["list"],
               "expect_rc": 99, "network": False}
        ok, _ = run_one(bad)
        report("selftest: 错误期望必须被判失败", not ok, [] if not ok else ["未判失败"])
        if ok:
            failed += 1

    print(f"共 {total} 项，失败 {failed} 项")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))