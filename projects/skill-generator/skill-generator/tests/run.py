#!/usr/bin/env python3
"""对话级测试：造沙箱目录，跑 validate.py 或指定脚本，断言结果。

用法: python3 tests/run.py [-g 组] [-i 用例ID] [--list]
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
VALIDATOR = SKILL / "scripts" / "validate.py"
SCRIPTS = SKILL / "scripts"
CASES = HERE / "cases.json"
SANDBOX = Path("/tmp/skill-generator-test")

sys.path.insert(0, str(SKILL / "scripts"))
import validate  # noqa: E402


def build(case_dir: Path, files: dict) -> None:
    for rel, content in files.items():
        p = case_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


def run_case(case, verbose=False) -> bool:
    cid = case["id"]
    root = SANDBOX / cid
    shutil.rmtree(root, ignore_errors=True)
    if case.get("no_dir"):
        target = root / "missing"
    else:
        name = case.get("dir_name", "demo")
        target = root / name
        target.mkdir(parents=True)
        build(target, case.get("files", {}))
    # parent_files：在技能目录的上一层造工程层文件，用于验「两层目录」检查
    if case.get("parent_files"):
        build(root, case["parent_files"])

    # 技能目录必须在 git 仓库里（validate 的硬要求）。沙箱里 git init 一下，
    # 但沙箱天然是脏的，所以验证一律带 --allow-dirty。
    if not case.get("no_dir") and not case.get("no_git"):
        subprocess.run(["git", "init", "-q", str(root)], capture_output=True, text=True)

    script = case.get("script")
    if script:
        # script 用例：把 {dir} 换成沙箱里的目标目录，整个工程结构由 files 造出来
        cmd = [sys.executable, str(SCRIPTS / script)]
        cmd += [a.replace("{dir}", str(target)) for a in case.get("args", [])]
        cmd += case.get("extra", [])
    else:
        cmd = [sys.executable, str(VALIDATOR), str(target), "--allow-dirty"] + case.get("extra", [])
    r = subprocess.run(cmd, capture_output=True, text=True)
    out = r.stdout + r.stderr

    fails = []
    if r.returncode != case["rc"]:
        fails.append(f"rc={r.returncode}，期望 {case['rc']}")
    for s in case.get("has", []):
        if s not in out:
            fails.append(f"输出缺少 {s!r}")
    for s in case.get("hasnt", []):
        if s in out:
            fails.append(f"输出不应包含 {s!r}")
    if case.get("json_ok"):
        try:
            data = json.loads(r.stdout)
            if case.get("json_ok_key") and case["json_ok_key"] not in data:
                fails.append(f"JSON 缺少键 {case['json_ok_key']}")
        except json.JSONDecodeError as e:
            fails.append(f"--json 输出不是合法 JSON: {e}")
    if case.get("errors_count") is not None:
        errs, _ = validate.check(target) if target.is_dir() else ([], [])
        if len(errs) != case["errors_count"]:
            fails.append(f"ERROR 数 {len(errs)}，期望 {case['errors_count']}")

    for rel in case.get("exists", []):
        if not (target / rel).exists():
            fails.append(f"磁盘上应存在 {rel}")
    for rel in case.get("absent", []):
        if (target / rel).exists():
            fails.append(f"磁盘上不应存在 {rel}")

    status = "✓" if not fails else "✗"
    print(f"| {cid} | {case.get('group','-')} | {case['name']} | {status} | {'；'.join(fails)} |")
    if verbose:
        print("    " + out.strip().replace("\n", "\n    ")[:400])
    return not fails


def main() -> int:
    argv = sys.argv[1:]
    group = argv[argv.index("-g") + 1] if "-g" in argv else None
    only = argv[argv.index("-i") + 1].split(",") if "-i" in argv else None
    data = json.loads(CASES.read_text(encoding="utf-8"))
    cases = data["cases"]
    if group:
        cases = [c for c in cases if c.get("group") == group]
    if only:
        cases = [c for c in cases if c["id"] in only]
    if "--list" in argv:
        for c in cases:
            print(c["id"], c["name"])
        return 0

    SANDBOX.mkdir(parents=True, exist_ok=True)
    print("| # | 组 | 场景 | 结果 | 失败原因 |")
    print("|---|---|---|---|---|")
    ok = sum(1 for c in cases if run_case(c, "-v" in argv))
    print(f"\n合计 {len(cases)} 项，失败 {len(cases) - ok} 项")
    return 0 if ok == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
