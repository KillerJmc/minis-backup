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
        "user": {"nickname": "N", "phone": "136****0565", "group": "Lite", "banned": False},
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
    if "亿" not in out:
        problems.append("超过 1 亿未切到亿单位")
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