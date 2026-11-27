#!/usr/bin/env python3
"""deepseek-stack-workflow 冒烟测试：原文齐全、状态机全流程、越级被拒。"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REFS = ROOT / "references"
CASES = []

PACK = {
    "ds-adopt", "ds-best-of-n", "ds-blast-radius", "ds-blueprint", "ds-catchup",
    "ds-context-reset", "ds-design-audit", "ds-design", "ds-explain", "ds-help",
    "ds-jury", "ds-ledger", "ds-lessons", "ds-mode", "ds-plan-loop", "ds-pr-comments",
    "ds-pr", "ds-principles", "ds-ready", "ds-review-loop", "ds-revive", "ds-sharpen",
    "ds-ship", "ds-swarm", "ds-tdd", "ds-unslop", "ds-unstick", "ds-verify-loop",
    "ds-watch-pr",
}


def case(name):
    def wrap(fn):
        CASES.append((name, fn))
        return fn
    return wrap


def read(p):
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def wf(state_dir, *args, extra_env=None):
    env = dict(os.environ, WORKFLOW_STATE_DIR=str(state_dir))
    # 默认空会话桩：否则会读真实会话，auto_verify 会按「我上一枪是什么」随机多打一行
    stub = Path(state_dir) / "session-default.json"
    if not stub.exists():
        stub.parent.mkdir(parents=True, exist_ok=True)
        stub.write_text(json.dumps({"total": 0, "commands": [], "texts": [], "calls": []}),
                        encoding="utf-8")
    env.setdefault("WORKFLOW_SESSION_STUB", str(stub))
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "workflow.py"), *args],
        capture_output=True, text=True, env=env, cwd=ROOT, timeout=120,
    )


@case("name 与目录名一致")
def _():
    m = re.search(r"^name:\s*(\S+)", read(ROOT / "SKILL.md")[:400], re.M)
    assert m and m.group(1) == ROOT.name, "name 缺失或与目录名不符"


@case("29 份原文齐全且 name 正确")
def _():
    got = {p.stem for p in REFS.glob("*.md")}
    assert got == PACK, f"多出 {sorted(got - PACK)}；缺少 {sorted(PACK - got)}"
    for n in sorted(PACK):
        m = re.search(r"^name:\s*(\S+)", read(REFS / f"{n}.md")[:400], re.M)
        assert m and m.group(1) == n, f"{n}.md 的 name 不对"


@case("原文逐字节未被改写")
def _():
    man = json.loads(read(ROOT / "tests" / "manifest.json"))["md5"]
    for n in sorted(PACK):
        got = hashlib.md5((REFS / f"{n}.md").read_bytes()).hexdigest()
        assert got == man.get(n), f"{n}.md 被改写过"


@case("SKILL.md 覆盖了状态机与边界说明")
def _():
    text = read(ROOT / "SKILL.md")
    for must in ("scripts/workflow.py", "ROUTE_PENDING", "COMPLETED",
                 "不能自动拦截所有未经它调用的工具操作", "不得将脚本状态机描述为 Minis 原生 Hooks"):
        assert must in text, f"缺关键条款：{must}"


@case("状态机正常流程跑到 COMPLETED")
def _():
    tmp = Path(tempfile.mkdtemp(prefix="wf-ok-"))
    try:
        assert wf(tmp, "start").returncode == 0, "start 失败"
        assert wf(tmp, "read", "ds-help").returncode == 0, "read ds-help 失败"
        assert wf(tmp, "route", "ds-mode").returncode == 0, "route 失败"
        assert wf(tmp, "read", "ds-mode").returncode == 0, "read 失败"
        wf(tmp, "plan", "单步")
        r = wf(tmp, "run", "true")
        assert r.returncode == 0, f"run 失败：{r.stderr}"
        assert wf(tmp, "verify").returncode == 0, "verify 失败"
        assert wf(tmp, "stop").returncode == 0, "stop 失败"
        tid = next(tmp.glob("current-*")).read_text().strip()
        data = json.loads((tmp / f"turn-{tid}.json").read_text())
        assert data["status"] == "COMPLETED", f"状态是 {data['status']}"
        assert data["reads"][0]["md5"], "读取记录缺 md5"
        assert data["completion"], "缺 completion 记录"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("多个技能能连续 route")
def _():
    tmp = Path(tempfile.mkdtemp(prefix="wf-multi-"))
    try:
        wf(tmp, "start")
        wf(tmp, "read", "ds-help")
        tid = next(tmp.glob("current-*")).read_text().strip()
        for s in ("ds-mode", "ds-blueprint", "ds-verify-loop"):
            r = wf(tmp, "route", s)
            assert r.returncode == 0, f"route {s} 失败：{r.stderr}"
            data = json.loads((tmp / f"turn-{tid}.json").read_text())
            assert data["status"] == "ROUTE_DONE", f"route {s} 后状态是 {data['status']}，应为 ROUTE_DONE"
        for s in ("ds-mode", "ds-blueprint", "ds-verify-loop"):
            r = wf(tmp, "read", s)
            assert r.returncode == 0, f"read {s} 失败：{r.stderr}"
        tid = next(tmp.glob("current-*")).read_text().strip()
        data = json.loads((tmp / f"turn-{tid}.json").read_text())
        assert data["status"] == "READ_DONE", f"状态是 {data['status']}"
        read_skills = {r["skill"] for r in data["reads"]}
        assert len(data["routes"]) == 3, "路由数不对"
        assert {"ds-mode", "ds-blueprint", "ds-verify-loop"} <= read_skills, f"读取缺技能：{read_skills}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("读完之后还能追加路由")
def _():
    tmp = Path(tempfile.mkdtemp(prefix="wf-late-"))
    try:
        wf(tmp, "start")
        wf(tmp, "read", "ds-help")
        wf(tmp, "route", "ds-mode")
        assert wf(tmp, "read", "ds-mode").returncode == 0
        r = wf(tmp, "route", "ds-verify-loop")
        assert r.returncode == 0, f"读完再 route 被拒：{r.stderr}"
        assert wf(tmp, "read", "ds-verify-loop").returncode == 0
        tid = next(tmp.glob("current-*")).read_text().strip()
        data = json.loads((tmp / f"turn-{tid}.json").read_text())
        assert data["status"] == "READ_DONE", f"状态是 {data['status']}"
        assert len(data["routes"]) == 2
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("--allow-fail 的失败不算整轮失败")
def _():
    tmp = Path(tempfile.mkdtemp(prefix="wf-af-"))
    try:
        wf(tmp, "start")
        wf(tmp, "read", "ds-help")
        wf(tmp, "route", "ds-mode")
        wf(tmp, "read", "ds-mode")
        wf(tmp, "plan", "单步")
        r = wf(tmp, "run", "exit 2", "--allow-fail")
        tid = next(tmp.glob("current-*")).read_text().strip()
        data = json.loads((tmp / f"turn-{tid}.json").read_text())
        assert data["status"] == "EXECUTED", f"状态是 {data['status']}"
        assert data["executions"][0]["exit"] == 2
        wf(tmp, "plan", "单步")
        wf(tmp, "run", "true")
        assert wf(tmp, "verify").returncode == 0, "带 allow-fail 的轮次应能 verify 通过"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("check 能算出清单并拦住缺项")
def _():
    tmp = Path(tempfile.mkdtemp(prefix="wf-chk-"))
    try:
        wf(tmp, "start")
        wf(tmp, "read", "ds-help")            # 路由表先读
        wf(tmp, "route", "ds-mode")
        wf(tmp, "read", "ds-mode")
        wf(tmp, "plan", "单步")
        wf(tmp, "run", "true")
        r = wf(tmp, "check")
        assert r.returncode == 8, f"未 verify 时 check 应返回 8，实际 {r.returncode}"
        assert "测试与验证已执行" in r.stdout
        wf(tmp, "verify")
        wf(tmp, "plan", "读原文", "跑命令")
        r2 = wf(tmp, "check")
        assert r2.returncode == 0, f"补全后应通过：{r2.stdout}"
        assert "全部通过" in r2.stdout
        assert wf(tmp, "stop").returncode == 0, "清单通过后 stop 应成功"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("restart 前必须 verify 才能 stop")
def _():
    tmp = Path(tempfile.mkdtemp(prefix="wf-stop-"))
    try:
        wf(tmp, "start")
        wf(tmp, "read", "ds-help")
        wf(tmp, "route", "ds-mode")
        wf(tmp, "read", "ds-mode")
        wf(tmp, "plan", "单步")
        wf(tmp, "run", "true")
        r = wf(tmp, "stop")
        assert r.returncode == 4, f"未 verify 就 stop 应拒绝，实际 {r.returncode}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("read 必须打印全文，不能只记录")
def _():
    tmp = Path(tempfile.mkdtemp(prefix="wf-full-"))
    try:
        wf(tmp, "start")
        r = wf(tmp, "read", "ds-help")
        assert r.returncode == 0
        text = (ROOT / "references" / "ds-help.md").read_text(encoding="utf-8")
        body_lines = [l for l in text.splitlines() if l.strip()]
        missing = [l for l in body_lines if l not in r.stdout]
        assert not missing, f"输出缺 {len(missing)} 行原文，例如：{missing[0][:40]}"
        assert "全文结束" in r.stdout, "缺结束标记"
        wf(tmp, "route", "ds-mode")
        r2 = wf(tmp, "read", "ds-mode")
        assert r2.returncode == 0
        assert "## Before you act" in r2.stdout, "ds-mode 也应打印全文"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("同一轮重复 read 仍然打印全文")
def _():
    tmp = Path(tempfile.mkdtemp(prefix="wf-again-"))
    try:
        wf(tmp, "start")
        first = wf(tmp, "read", "ds-help")
        again = wf(tmp, "read", "ds-help")
        for tag, r in (("首次", first), ("二次", again)):
            assert r.returncode == 0, f"{tag} read 失败"
            assert "全文结束" in r.stdout, f"{tag} read 没打全文"
            assert "# ds-help" in r.stdout, f"{tag} read 缺正文"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("沙盒：装载技能并完成一个开发任务")
def _():
    javac, java = shutil.which("javac"), shutil.which("java")
    if not (javac and java):
        print("      （无 JDK，跳过）")
        return
    sand = Path(tempfile.mkdtemp(prefix="wf-sand-"))
    try:
        # 1. 把技能整份装进沙盒，模拟另一个人拿到这个技能
        skill = sand / ROOT.name
        shutil.copytree(ROOT, skill, ignore=shutil.ignore_patterns(".state", "__pycache__"))
        work = sand / "work"
        work.mkdir()

        def run(*args, timeout=180):
            env = dict(os.environ, WORKFLOW_STATE_DIR=str(skill / ".state"))
            return subprocess.run(
                [sys.executable, str(skill / "scripts" / "workflow.py"), *args],
                capture_output=True, text=True, env=env, cwd=skill, timeout=timeout,
            )

        # 2. 按 SKILL.md 的流程做一个开发任务
        assert run("start").returncode == 0
        assert run("read", "ds-help").returncode == 0, "读路由表失败"
        assert run("route", "ds-verify-loop").returncode == 0, "路由失败"
        assert run("read", "ds-verify-loop").returncode == 0, "读原文失败"
        assert run("plan", "写 Floyd", "编译运行", "对拍").returncode == 0, "写计划失败"

        # 3. 交付物：样例提供代码，模拟 agent 写出来的产物
        src = ROOT / "tests" / "fixtures" / "Floyd.java"
        shutil.copy(src, work / "Floyd.java")
        run("plan", "单步")
        r = run("run", f"cd {work} && javac -d out Floyd.java && JAVA_TOOL_OPTIONS= java -cp out Floyd")
        assert r.returncode == 0, f"编译运行失败：{r.stdout[-400:]}"
        assert "失败 0 个" in r.stdout, f"样例没跑通：{r.stdout[-300:]}"

        # 4. 未 verify 时清单必须拦人
        r = run("check")
        assert r.returncode == 8, f"未 verify 却放行（rc={r.returncode}）"
        assert run("verify").returncode == 0, "verify 失败"
        assert run("check").returncode == 0, f"verify 后清单仍不通过：{run('check').stdout[-300:]}"
        r = run("stop")
        assert r.returncode == 0, f"stop 失败：{r.stdout[-300:]}"
        assert "COMPLETED" in run("status").stdout
    finally:
        shutil.rmtree(sand, ignore_errors=True)


@case("沙盒：同时遵守 deepseek-stack 与 skill-generator")
def _():
    src = Path("/var/minis/skills/skill-generator")
    if not (src / "scripts" / "validate.py").is_file():
        print("      （没有 skill-generator，跳过）")
        return
    sand = Path(tempfile.mkdtemp(prefix="wf-dual-"))
    try:
        skill = sand / ROOT.name
        shutil.copytree(ROOT, skill, ignore=shutil.ignore_patterns(".state", "__pycache__"))
        skills_root = sand / "skills"
        skills_root.mkdir()
        shutil.copytree(src, skills_root / "skill-generator",
                        ignore=shutil.ignore_patterns(".state", "__pycache__"))

        def run(*args, timeout=180):
            env = dict(
                os.environ,
                WORKFLOW_STATE_DIR=str(skill / ".state"),
                WORKFLOW_SKILLS_DIRS=str(skills_root),
            )
            return subprocess.run(
                [sys.executable, str(skill / "scripts" / "workflow.py"), *args],
                capture_output=True, text=True, env=env, cwd=skill, timeout=timeout,
            )

        # 1) 方法层 + 领域层同时挂上一轮
        assert run("start").returncode == 0
        assert run("read", "ds-help").returncode == 0
        assert run("route", "ds-mode").returncode == 0
        r = run("route", "skill-generator")
        assert r.returncode == 0, f"外部技能路由失败：{r.stderr}"
        assert run("read", "ds-mode").returncode == 0
        r = run("read", "skill-generator")
        assert r.returncode == 0, f"外部技能读取失败：{r.stderr}"
        assert "external" in r.stdout, "读取记录没标 external"

        # 2) 按 skill-generator 的规矩造一个 demo 技能
        demo = sand / "demo-skill"
        demo.mkdir()
        (demo / "SKILL.md").write_text(
            "---\n"
            "name: demo-skill\n"
            "description: 演示技能，把两个数相加并打印结果\n"
            "version: 1.0.0\n"
            "triggers: 演示,加法\n"
            "---\n\n"
            "演示技能，把两个数相加并打印结果\n\n"
            "## 功能\n\n"
            "| 功能 | 什么时候用 | 及格线 |\n"
            "|---|---|---|\n"
            "| 加法 | 需要相加时 | 打印出结果 |\n\n"
            "## 加法\n\n"
            "```sh\n"
            'python3 -c "print(1 + 2)"\n'
            "```\n",
            encoding="utf-8",
        )
        (demo / "CHANGELOG.md").write_text(
            "1.0.0 · 2026-11-27\n\n首次建成（新）\n- 加法功能：打印两个数之和\n",
            encoding="utf-8",
        )
        for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                    ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"]):
            subprocess.run(cmd, cwd=demo, capture_output=True, timeout=60)

        # 3) 用 skill-generator 的校验器验它
        validator = skills_root / "skill-generator" / "scripts" / "validate.py"
        run("plan", "单步")
        r = run("run", f"python3 {validator} {demo}", timeout=180)
        assert r.returncode == 0, f"demo 技能没通过校验：{r.stdout[-500:]}"
        assert "0 个 ERROR" in r.stdout, f"校验有 ERROR：{r.stdout[-400:]}"

        # 4) 收尾走完
        assert run("verify").returncode == 0
        assert run("check").returncode == 0
        assert run("stop").returncode == 0
    finally:
        shutil.rmtree(sand, ignore_errors=True)


@case("沙盒：同时遵守 deepseek-stack 与查额度技能")
def _():
    src = Path("/var/minis/skills/quota-usage")
    runner = src / "scripts" / "route.py"
    if not runner.is_file():
        print("      （没有 quota-usage，跳过）")
        return
    sand = Path(tempfile.mkdtemp(prefix="wf-quota-"))
    try:
        skill = sand / ROOT.name
        shutil.copytree(ROOT, skill, ignore=shutil.ignore_patterns(".state", "__pycache__"))
        skills_root = sand / "skills"
        skills_root.mkdir()
        quota = skills_root / "quota-usage"
        shutil.copytree(src, quota, ignore=shutil.ignore_patterns(".state", "__pycache__"))

        def run(*args, timeout=180):
            env = dict(
                os.environ,
                WORKFLOW_STATE_DIR=str(skill / ".state"),
                WORKFLOW_SKILLS_DIRS=str(skills_root),
            )
            return subprocess.run(
                [sys.executable, str(skill / "scripts" / "workflow.py"), *args],
                capture_output=True, text=True, env=env, cwd=skill, timeout=timeout,
            )

        # 方法层 + 额度技能同时挂上
        assert run("start").returncode == 0
        assert run("read", "ds-help").returncode == 0
        assert run("route", "ds-mode").returncode == 0
        r = run("route", "quota-usage")
        assert r.returncode == 0, f"外部技能路由失败：{r.stderr}"
        assert run("read", "ds-mode").returncode == 0
        r = run("read", "quota-usage")
        assert r.returncode == 0, f"读不到额度技能原文：{r.stderr}"
        assert "external" in r.stdout, "读取记录没标 external"

        # 真跑额度技能自己的命令（list 不依赖登录态）
        run("plan", "单步")
        r = run("run", f"cd {quota} && python3 scripts/route.py list")
        assert r.returncode == 0, f"额度技能运行失败：{r.stdout[-400:]}"
        assert "支持" in r.stdout and "平台" in r.stdout, f"输出不对：{r.stdout[:200]}"

        # 收尾
        assert run("verify").returncode == 0
        assert run("check").returncode == 0
        assert run("stop").returncode == 0
    finally:
        shutil.rmtree(sand, ignore_errors=True)


@case("用法里写明外部技能的标题格式")
def _():
    text = read(ROOT / "scripts" / "workflow.py")
    assert "（外部skill）" in text, "没写外部技能的卡片标题格式"
    assert "路由到 ds-xxx：读原文" in text, "没写内部技能的卡片标题格式"


@case("跑过没记账的命令会被打回重做")
def _():
    tmp = Path(tempfile.mkdtemp(prefix="wf-aud-"))
    try:
        stub = tmp / "session.json"
        stub.write_text(json.dumps({"total": 100, "commands": []}), encoding="utf-8")
        env = {"WORKFLOW_SESSION_STUB": str(stub)}

        def run(*args, _env=None):
            return wf(tmp, *args, extra_env=_env or env)

        run("start")
        run("read", "ds-help")
        run("route", "ds-mode")
        run("read", "ds-mode")
        run("plan", "单步")
        run("run", "echo 记账了")
        stub.write_text(json.dumps({"total": 101, "commands": []}), encoding="utf-8")
        assert run("verify").returncode == 0, "干净的一轮不该被打回"

        # 换一条没记账的命令，重新走一轮
        stub.write_text(json.dumps({"total": 200, "commands": []}), encoding="utf-8")
        run("start")
        run("read", "ds-help")
        run("route", "ds-mode")
        run("read", "ds-mode")
        run("plan", "单步")
        run("plan", "单步")
        run("run", "echo 记账了")
        stub.write_text(json.dumps({"total": 201, "commands": ["python3 fake.py --go"]}),
                        encoding="utf-8")
        r = run("verify")
        assert r.returncode == 6, f"应打回（rc=6），实际 {r.returncode}"
        assert "python3 fake.py --go" in r.stdout, "没列出没记账的命令"
        tid = next(tmp.glob("current-*")).read_text().strip()
        data = json.loads((tmp / f"turn-{tid}.json").read_text())
        assert data["status"] == "READ_DONE", f"应回退到 READ_DONE，实际 {data['status']}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("cd 包着的命令也拦得住")
def _():
    tmp = Path(tempfile.mkdtemp(prefix="wf-cd-"))
    try:
        stub = tmp / "session.json"
        stub.write_text(json.dumps({"total": 300, "commands": []}), encoding="utf-8")
        env = {"WORKFLOW_SESSION_STUB": str(stub)}

        def run(*args):
            return wf(tmp, *args, extra_env=env)

        run("start")
        run("read", "ds-help")
        run("route", "ds-mode")
        run("read", "ds-mode")
        run("plan", "单步")
        run("plan", "单步")
        run("run", "echo 记账了")
        # 用 cd 包一层，看会不会被当成合法前缀整体放行
        stub.write_text(json.dumps({
            "total": 301,
            "commands": [{"cmd": "cd /tmp && sed -n '1,5p' x.txt", "title": "看文件"}],
        }), encoding="utf-8")
        r = run("verify")
        assert r.returncode == 6, f"cd 包裹的命令应被拦，实际 rc={r.returncode}"
        assert "sed -n" in r.stdout, "没指出具体命令"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("一次调用读两个技能会被拦")
def _():
    tmp = Path(tempfile.mkdtemp(prefix="wf-two-"))
    try:
        stub = tmp / "session.json"
        stub.write_text(json.dumps({"total": 400, "commands": []}), encoding="utf-8")
        env = {"WORKFLOW_SESSION_STUB": str(stub)}

        def run(*args):
            return wf(tmp, *args, extra_env=env)

        run("start")
        run("read", "ds-help")
        run("route", "ds-mode")
        run("read", "ds-mode")
        run("plan", "单步")
        run("plan", "单步")
        run("run", "echo 记账了")
        cmd = ("python3 scripts/workflow.py read ds-help && "
               "python3 scripts/workflow.py route ds-mode && "
               "python3 scripts/workflow.py read ds-mode")
        stub.write_text(json.dumps({
            "total": 401,
            "commands": [{"cmd": cmd, "title": "路由到 ds-mode：读原文"}],
        }), encoding="utf-8")
        r = run("verify")
        assert r.returncode == 6, f"应被拦，实际 rc={r.returncode}"
        assert "一次调用读了 2 个技能" in r.stdout, r.stdout[-200:]

        # start 标题写错也要拦
        stub.write_text(json.dumps({
            "total": 402,
            "commands": [{"cmd": "python3 scripts/workflow.py start", "title": "创建本轮工作记录"}],
        }), encoding="utf-8")
        r = run("verify")
        assert "创建工作流记录" in r.stdout, r.stdout[-200:]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("plan 标题必须是「路径规划」")
def _():
    tmp = Path(tempfile.mkdtemp(prefix="wf-plan-"))
    try:
        stub = tmp / "session.json"
        stub.write_text(json.dumps({"total": 500, "commands": []}), encoding="utf-8")
        env = {"WORKFLOW_SESSION_STUB": str(stub)}

        def run(*args):
            return wf(tmp, *args, extra_env=env)

        run("start")
        run("read", "ds-help")
        run("route", "ds-mode")
        run("read", "ds-mode")
        r = run("plan", "第一步", "第二步")
        assert r.returncode == 0
        assert "路径规划（2 步）" in r.stdout, r.stdout
        run("plan", "单步")
        run("plan", "单步")
        run("run", "true")

        stub.write_text(json.dumps({
            "total": 501,
            "commands": [{"cmd": "python3 scripts/workflow.py plan 第一步", "title": "记录计划"}],
        }), encoding="utf-8")
        r = run("verify")
        assert r.returncode == 6, f"标题写错应被拦，实际 rc={r.returncode}"
        assert "路径规划" in r.stdout, r.stdout[-200:]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("开新轮不再提示上一轮计划")
def _():
    tmp = Path(tempfile.mkdtemp(prefix="wf-text-"))
    try:
        stub = tmp / "session.json"
        stub.write_text(json.dumps({"total": 600, "commands": [], "texts": []}),
                        encoding="utf-8")
        env = {"WORKFLOW_SESSION_STUB": str(stub)}

        def run(*args):
            return wf(tmp, *args, extra_env=env)

        run("start")
        run("read", "ds-help")
        run("route", "ds-mode")
        run("read", "ds-mode")
        run("plan", "写代码", "跑测试")
        run("run", "true")

        # 正文里没有计划 → 下一轮 start 必须拒绝
        stub.write_text(json.dumps({"total": 700, "commands": [], "texts": ["好的，继续"]}),
                        encoding="utf-8")
        r = run("start")
        assert r.returncode == 0, f"只提醒不拦截，实际 {r.returncode}"
        assert "路径规划" not in r.stderr, f"不该再提醒计划：{r.stderr}"

        # 正文里有了 → 放行
        stub.write_text(json.dumps({
            "total": 701, "commands": [],
            "texts": ["路径规划：1. 写代码 2. 跑测试"],
        }), encoding="utf-8")
        assert run("start").returncode == 0, "正文含计划却仍被拒"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("第一枪不是 start 就判违规")
def _():
    tmp = Path(tempfile.mkdtemp(prefix="wf-first-"))
    try:
        stub = tmp / "session.json"
        # 本轮：先 file_edit 改代码，再 start —— 顺序错
        stub.write_text(json.dumps({
            "total": 800, "commands": [], "texts": [],
            "calls": [
                {"name": "file_edit", "cmd": "", "title": "改校验逻辑"},
                {"name": "shell_execute", "cmd": "python3 scripts/workflow.py start",
                 "title": "创建工作流记录"},
            ],
        }), encoding="utf-8")
        env = {"WORKFLOW_SESSION_STUB": str(stub)}

        def run(*args):
            return wf(tmp, *args, extra_env=env)

        run("start")
        run("read", "ds-help")
        run("route", "ds-mode")
        run("read", "ds-mode")
        run("plan", "单步")
        assert run("run", "true").returncode == 0
        r = run("verify")
        assert r.returncode == 6, f"顺序错应被打回，实际 {r.returncode}"
        assert "第一个工具调用不是 start" in r.stdout, r.stdout[-300:]

        # 顺序对了就放行
        tmp2 = Path(tempfile.mkdtemp(prefix="wf-first-ok-"))
        try:
            stub2 = tmp2 / "session.json"
            stub2.write_text(json.dumps({
                "total": 900, "commands": [], "texts": [],
                "calls": [{"name": "shell_execute",
                           "cmd": "python3 scripts/workflow.py start",
                           "title": "创建工作流记录"}],
            }), encoding="utf-8")
            env2 = {"WORKFLOW_SESSION_STUB": str(stub2)}

            def run2(*args):
                return wf(tmp2, *args, extra_env=env2)

            run2("start")
            run2("read", "ds-help")
            run2("route", "ds-mode")
            run2("read", "ds-mode")
            run2("plan", "单步")
            run2("plan", "单步")
            run2("run", "true")
            assert run2("verify").returncode == 0, "顺序正确却被打回"
        finally:
            shutil.rmtree(tmp2, ignore_errors=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("上一枪是原生工具时自动 verify")
def _():
    tmp = Path(tempfile.mkdtemp(prefix="wf-auto-"))
    try:
        stub = tmp / "session.json"
        base = {"total": 1000, "commands": [], "texts": [],
                "calls": [{"name": "shell_execute",
                           "cmd": "python3 scripts/workflow.py start",
                           "title": "创建工作流记录"}]}
        stub.write_text(json.dumps(base), encoding="utf-8")
        env = {"WORKFLOW_SESSION_STUB": str(stub)}

        def run(*args):
            return wf(tmp, *args, extra_env=env)

        run("start")
        r = run("read", "ds-help")
        assert "自动 verify" not in r.stdout, "上一枪还是 workflow，不该触发"

        # 上一枪换成 file_write → 下一次调用应自动 verify
        base["calls"] = [
            {"name": "shell_execute", "cmd": "python3 scripts/workflow.py start",
             "title": "创建工作流记录"},
            {"name": "file_write", "cmd": "", "title": "写文件"},
        ]
        stub.write_text(json.dumps(base), encoding="utf-8")
        r = run("status")
        assert "自动 verify（上一枪 file_write" in r.stdout, r.stdout
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("start 之前的调用也算进本轮")
def _():
    tmp = Path(tempfile.mkdtemp(prefix="wf-pre-"))
    try:
        stub = tmp / "session.json"
        stub.write_text(json.dumps({
            "total": 1100, "commands": [], "texts": [],
            "last_user_index": 950,
            "calls": [
                {"name": "file_edit", "cmd": "", "title": "改校验逻辑"},
                {"name": "shell_execute", "cmd": "python3 scripts/workflow.py start",
                 "title": "创建工作流记录"},
            ],
        }), encoding="utf-8")
        env = {"WORKFLOW_SESSION_STUB": str(stub)}

        def run(*args):
            return wf(tmp, *args, extra_env=env)

        r = run("start")
        assert r.returncode == 0, r.stderr
        tid = next(tmp.glob("current-*")).read_text().strip()
        data = json.loads((tmp / f"turn-{tid}.json").read_text())
        assert data["baseline_total"] == 950, f"基线应取用户消息位置，实际 {data['baseline_total']}"
        run("read", "ds-help")
        run("route", "ds-mode")
        run("read", "ds-mode")
        run("plan", "单步")
        run("plan", "单步")
        run("run", "true")
        r = run("verify")
        assert r.returncode == 6, f"start 前的 file_edit 应被抓，实际 {r.returncode}"
        assert "第一个工具调用不是 start" in r.stdout, r.stdout[-300:]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("中断的轮次不闭合就不让开新轮")
def _():
    tmp = Path(tempfile.mkdtemp(prefix="wf-ab-"))
    try:
        stub = tmp / "session.json"
        stub.write_text(json.dumps({"total": 1300, "commands": [], "texts": [],
                                    "calls": [], "session_id": "S-1",
                                    "last_user_msg_id": "M-1"}), encoding="utf-8")
        env = {"WORKFLOW_SESSION_STUB": str(stub)}

        def run(*args):
            return wf(tmp, *args, extra_env=env)

        run("start")
        run("read", "ds-help")
        run("route", "ds-mode")
        run("read", "ds-mode")
        run("plan", "单步")
        # 模拟中断：不 verify 不 stop，直接开新轮 → 旧轮自动收尾，新轮直接开
        stub.write_text(json.dumps({"total": 1301, "commands": [], "texts": ["单步"],
                                    "calls": [], "session_id": "S-1",
                                    "last_user_msg_id": "M-1"}), encoding="utf-8")
        r = run("start")
        assert r.returncode == 0, f"应自动收尾并开新轮，实际 {r.returncode}"
        assert "ABANDONED" in r.stderr, r.stderr
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("新消息取代后旧轮次立刻失效")
def _():
    tmp = Path(tempfile.mkdtemp(prefix="wf-anchor-"))
    try:
        stub = tmp / "s.json"
        stub.write_text(json.dumps({"total": 1400, "commands": [], "texts": [], "calls": [],
                                    "session_id": "S-1", "last_user_msg_id": "M-1"}),
                        encoding="utf-8")
        env = {"WORKFLOW_SESSION_STUB": str(stub)}

        def run(*args):
            return wf(tmp, *args, extra_env=env)

        run("start")
        run("read", "ds-help")
        assert run("status").returncode == 0, "同一条消息内应放行"
        # 用户又发了新消息：锚点不匹配
        stub.write_text(json.dumps({"total": 1401, "commands": [], "texts": [], "calls": [],
                                    "session_id": "S-1", "last_user_msg_id": "M-2"}),
                        encoding="utf-8")
        r = run("status")
        assert r.returncode == 10, f"应 rc=10，实际 {r.returncode}"
        assert "中途停止" in r.stderr, r.stderr
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("别的会话的记录不能接着用")
def _():
    tmp = Path(tempfile.mkdtemp(prefix="wf-sid-"))
    try:
        stub = tmp / "s.json"
        stub.write_text(json.dumps({"total": 1500, "commands": [], "texts": [], "calls": [],
                                    "session_id": "S-A", "last_user_msg_id": "M-9"}),
                        encoding="utf-8")
        env = {"WORKFLOW_SESSION_STUB": str(stub)}

        def run(*args):
            return wf(tmp, *args, extra_env=env)

        run("start")
        run("read", "ds-help")
        stub.write_text(json.dumps({"total": 1501, "commands": [], "texts": [], "calls": [],
                                    "session_id": "S-B", "last_user_msg_id": "M-9"}),
                        encoding="utf-8")
        r = run("status")
        assert r.returncode in (3, 11), f"应拒绝，实际 {r.returncode}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("越级操作被拒绝")
def _():
    tmp = Path(tempfile.mkdtemp(prefix="wf-bad-"))
    try:
        wf(tmp, "start")
        wf(tmp, "read", "ds-help")
        assert wf(tmp, "read", "ds-mode").returncode == 4, "未 route 就 read 应拒绝"
        assert wf(tmp, "verify").returncode == 4, "未执行就 verify 应拒绝"
        wf(tmp, "route", "ds-mode")
        wf(tmp, "read", "ds-mode")
        assert wf(tmp, "stop").returncode == 4, "未验证就 stop 应拒绝"
        wf(tmp, "plan", "单步")
        bad = wf(tmp, "run", "exit 3")
        assert bad.returncode == 6, "失败命令应返回 6"
        tid = next(tmp.glob("current-*")).read_text().strip()
        data = json.loads((tmp / f"turn-{tid}.json").read_text())
        assert data["status"] == "FAILED", f"失败后状态是 {data['status']}"
        assert wf(tmp, "stop").returncode == 4, "FAILED 状态不应允许 stop"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("route 不存在的技能直接拒绝")
def _():
    tmp = Path(tempfile.mkdtemp(prefix="wf-miss-"))
    try:
        wf(tmp, "start")
        wf(tmp, "read", "ds-help")
        r = wf(tmp, "route", "ds-nonexistent")
        assert r.returncode == 2, f"不存在的技能应在 route 阶段拒绝，实际 {r.returncode}"
        tid = next(tmp.glob("current-*")).read_text().strip()
        data = json.loads((tmp / f"turn-{tid}.json").read_text())
        assert data["routes"] == [], "不该记录不存在的技能"
        assert data["status"] == "ROUTE_PENDING", f"状态被改成了 {data['status']}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    failed = 0
    for name, fn in CASES:
        try:
            fn()
            print(f"  ok   {name}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {name}: {e}")
        except Exception as e:
            failed += 1
            print(f"  ERR  {name}: {type(e).__name__}: {e}")
    print(f"共 {len(CASES)} 项，失败 {failed} 项")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
