#!/usr/bin/env python3
"""project-workspace 端到端测试引擎（对话级）。

每条用例 = 一段对话：用户说了什么 → 助手该跑什么 → 输出对不对 → 磁盘结果对不对。
用例在 cases.json，本文件只做执行与判定。

用例结构：
  {
    "id": "C2", "group": "C", "name": "改项目名",
    "session_group": "新名", "link": "旧名", "prev": null,
    "setup": [...],                     // 沙箱预置
    "turns": [                          // 一轮 = 一句用户输入
      {
        "user": "我改项目名了",          // 用户原话（断言里会回显）
        "cmd": ["migrate"],             // 助手应该跑的命令
        "rc": 0,                        // 期望退出码
        "has": ["已迁移"],               // 输出必须含
        "hasnt": ["冲突"],               // 输出不得含
        "reply_has": ["新名"],           // 助手复述给用户的文本必须含
        "reply_hasnt": ["空目录"]        // 助手不得声称的内容
      }
    ],
    "assert": [["text", "路径", "内容"], ...]   // 最后对磁盘下结论
  }

用法：
  python3 tests/run.py [--list] [-g 组] [-i id1,id2] [-v]
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WS = str(HERE.parent / "scripts" / "ws.py")
CASES = Path(os.environ.get("WS_CASES", HERE / "cases.json"))
ROOT = Path(os.environ.get("WS_TEST_ROOT", "/tmp/ws-test/e2e"))
RESULTS = []


def env_for(tag, case):
    base = ROOT / tag
    e = {
        "WS_MOUNTS": str(base / "mounts"),
        "WS_APP_SKILLS": str(base / "app_skills"),
        "WS_APP_MEMORY": str(base / "app_memory"),
        "WS_LINK_FILE": str(base / "chat/.project"),
        "WS_PREV_FILE": str(base / "chat/.project-prev"),
        "PATH": os.environ["PATH"],
    }
    if "session_group" in case:
        e["WS_SESSION_GROUP"] = case["session_group"]
    if case.get("no_cli"):
        e["WS_CLI"] = str(base / "no-such-cli")
    return e


def sandbox(tag, case):
    base = ROOT / tag
    if base.exists():
        shutil.rmtree(base)
    (base / "chat").mkdir(parents=True)
    e = env_for(tag, case)
    if case.get("mount", "Minis") != "none":
        (Path(e["WS_MOUNTS"]) / case.get("mount", "Minis")).mkdir(parents=True, exist_ok=True)
    for item in case.get("setup", []):
        p = base / item["path"]
        if item["type"] == "dir":
            p.mkdir(parents=True, exist_ok=True)
        elif item["type"] == "file":
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(item.get("content", ""))
        elif item["type"] == "bytes":
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"x" * item.get("size", 0))
        elif item["type"] == "symlink":
            p.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(item["target"], p)
    if "link" in case:
        (base / "chat/.project").write_text(case["link"] + "\n")
    if "prev" in case:
        (base / "chat/.project-prev").write_text(case["prev"] + "\n")
    return base, e


def exec_turn(e, turn):
    cmd = turn.get("cmd") or []
    if turn.get("no_cmd"):
        return 0, "", ""
    p = subprocess.run([sys.executable, WS, *cmd], capture_output=True, text=True, env=e, timeout=90)
    return p.returncode, p.stdout, p.stderr


def count_files(p: Path):
    return sum(1 for x in p.rglob("*") if x.is_file()) if p.is_dir() else -1


def check(base, op, *args):
    if op == "rc":
        return True, ""
    path = (base / args[0]) if args else None
    if op == "exists":
        return path.exists(), ""
    if op == "absent":
        ok = not path.exists()
        return ok, f"{args[0]} {'已删除' if ok else '仍存在'}"
    if op == "file":
        return path.is_file(), ""
    if op == "dir":
        return path.is_dir(), ""
    if op == "text":
        want = args[1]
        got = path.read_text().rstrip("\n") if path.is_file() else "<缺失>"
        return got == want, f"内容={got[:40]!r}"
    if op == "notext":
        got = path.read_text() if path.is_file() else ""
        return args[1] not in got, f"含 {args[1]!r}" if args[1] in got else ""
    if op == "count":
        got = count_files(path)
        return got == int(args[1]), f"{got} 个文件"
    if op == "empty":
        ok = path.is_dir() and not any(path.iterdir())
        return ok, "" if ok else "非空"
    if op == "link":
        p = base / "chat/.project"
        got = p.read_text().strip() if p.is_file() else "<无>"
        return got == args[0], f"link={got}"
    if op == "noprev":
        ok = not (base / "chat/.project-prev").exists()
        return ok, "" if ok else "prev 残留"
    raise ValueError(f"未知断言 {op}")


def reply_of(out, turn):
    """模拟助手复述：按 SKILL 规则应逐行照抄工具输出里的事实行。"""
    lines = [ln for ln in out.splitlines() if ln.strip() and not ln.startswith("❌")]
    return "\n".join(lines)


def run_case(c):
    base, e = sandbox(c["id"], c)
    fails, transcript = [], []

    for t in c.get("turns", c.get("steps", [])):
        rc, o, er = exec_turn(e, t)
        cmd = " ".join(t.get("cmd") or ["<无命令>"])
        transcript.append(f"U: {t.get('user', '（未写用户输入）')}\nA: {cmd}")
        if "rc" in t and rc != t["rc"]:
            fails.append(f"[{cmd}] rc={rc}，期望 {t['rc']}")
        blob = o + er
        for s in t.get("has", []):
            if s not in blob:
                fails.append(f"[{cmd}] 输出缺少 {s!r}")
        for s in t.get("hasnt", []):
            if s in blob:
                fails.append(f"[{cmd}] 输出不该出现 {s!r}")
        rp = reply_of(o, t)
        for s in t.get("reply_has", []):
            if s not in rp:
                fails.append(f"[{cmd}] 复述缺少 {s!r}")
        for s in t.get("reply_hasnt", []):
            if s in rp:
                fails.append(f"[{cmd}] 复述不得出现 {s!r}")
        if t.get("user") is None:
            fails.append("用例缺 user 字段（端到端必须写明用户说了什么）")

    for a in c.get("assert", []):
        ok, msg = check(base, a[0], *a[1:])
        if not ok:
            fails.append(f"{a[0]}{list(a[1:])} 失败 {msg}")

    RESULTS.append(dict(id=c["id"], group=c.get("group", "?"), name=c["name"],
                        ok="✓" if not fails else "✗",
                        detail="；".join(dict.fromkeys(fails))[:170],
                        transcript=" ／ ".join(transcript)[:150]))
    return not fails


def main():
    if not CASES.is_file():
        print(f"用例文件缺失: {CASES}")
        return 2
    try:
        cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    except Exception as ex:
        print(f"用例文件损坏: {ex}")
        return 2

    argv = sys.argv[1:]
    only_group = argv[argv.index("-g") + 1] if "-g" in argv else None
    only_ids = argv[argv.index("-i") + 1].split(",") if "-i" in argv else None
    verbose = "-v" in argv
    selftest = "--selftest" in argv
    if "--list" in argv:
        for c in cases:
            n = len(c.get("turns", c.get("steps", [])))
            print(f"{c['id']:>7} [{c.get('group','?'):>3}] {n} 轮  {c['name']}")
        print(f"\n共 {len(cases)} 条")
        return 0

    for c in cases:
        if only_group and c.get("group") != only_group:
            continue
        if only_ids and c["id"] not in only_ids:
            continue
        try:
            run_case(c)
        except Exception as ex:
            RESULTS.append(dict(id=c["id"], group=c.get("group", "?"), name=c["name"],
                                ok="✗", detail=f"执行异常: {ex}", transcript=""))

    print("| # | 组 | 场景（用户说了什么 → 跑什么） | 结果 | 失败原因 |")
    print("|---|---|---|---|---|")
    for r in RESULTS:
        if verbose or r["ok"] == "✗":
            print(f"| {r['id']} | {r['group']} | {r['name']} ／ {r['transcript']} | {r['ok']} | {r['detail']} |")
        else:
            print(f"| {r['id']} | {r['group']} | {r['name']} | {r['ok']} | {r['detail']} |")
    bad = [r for r in RESULTS if r["ok"] == "✗"]
    print(f"\n合计 {len(RESULTS)} 项，失败 {len(bad)} 项")
    for r in bad:
        print(f"  ✗ [{r['group']}#{r['id']}] {r['name']} → {r['detail']}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
