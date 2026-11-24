#!/usr/bin/env python3
"""把已有工程整理成规范结构：先查名字，名字不对就停；对上才补文件。

工程层只建 PROJECT.md、PROGRESS.md、.gitignore、temp/；
不建 WORKFLOW.md，也不复制 deploy.py——流程与工具都由 skill-generator 提供。

用法:
    python3 normalize.py [工程目录] [--apply] [--json]
退出码:
    0 已合规，或 --apply 执行完成
    1 执行出错
    2 用法错误 / 找不到工程
    3 命名不一致，已停止（未改动任何文件）
"""
import json
import re
import subprocess
import sys
from pathlib import Path

MOUNTS = Path("/var/minis/mounts/Minis")
PROJECTS = MOUNTS / "projects"
LINK = Path("/var/minis/workspace/.project")

PROJECT_LAYER = ("PROJECT.md", "PROGRESS.md")
IGNORE_HEAD = [
    "__pycache__/",
    "*.pyc",
    ".DS_Store",
    "",
    "# 技能目录各自是独立 git 仓库，不纳入工程仓库",
]


def ignore_rules(skills: list[str]) -> list[str]:
    """只排除技能目录，其余一律入库（docs/、temp/、图片、压缩包都不挡）。"""
    return IGNORE_HEAD + [f"/{Path(s).name}/" for s in skills]

def make_project_md(project: Path, skills: list[str]) -> str:
    """按实际内容生成 PROJECT.md：目录树与上线链路用真实名字，不留占位。"""
    lines = ["projects/%s/" % project.name]
    for f, desc in (("PROJECT.md", "本文件：是什么、为什么这样设计"),
                    ("PROGRESS.md", "做到哪、下一步"),
                    (".gitignore", "只排除技能目录（其余一律入库）"),
                    ("temp/", "临时数据、中间稿（进工程 git）"),
                    ("docs/", "调研与长文档（有内容才建）")):
        if f == "docs/" and not (project / "docs").is_dir():
            continue
        lines.append("├── %-16s %s" % (f, desc))
    for s in skills:
        lines.append("└── %-16s 技能工作副本（独立 git 仓库）" % (s + "/"))
    tree = "\n".join(lines)
    skill = skills[0] if skills else "<技能名>"
    return f"""# {project.name} 工程

一句话定位：本工程管的是什么。

## 功能点（用户能主动触发的事）

| 功能 | 触发关键字 | 作用 |
|---|---|---|

## 关键决定

（暂无。踩到坑或做出取舍时追加，写清“曾经怎么做、结果如何、所以改成现在这样”）

## 目录

```
{tree}
```

## 上线链路

```
{skill}/（技能仓库：改 → 测 → commit）
      ↓ 共享 deploy.py（测绿才走）
/var/minis/skills/{skill}/            （App 权威源）
      ↓ ws.py sync --push
/var/minis/mounts/Minis/skills/{skill}/（外部镜像）
```

## 遗留

（暂无）
"""


PROGRESS_TMPL = """# {name} 进度

> 接手这个工程先读这里。设计理由在 `PROJECT.md`，不要重复。

## 当前状态

- 版本：待确认
- 阶段：结构刚整理完，待补充
- 下一步：确认技能内容与上线状态

## 待办

- [ ] 补齐 `PROJECT.md` 的功能点与关键决定
- [ ] 确认技能版本与线上是否一致

## 时间线

### {date} · 结构整理
- 由 `normalize.py` 按规范补齐工程层文件与临时目录。
"""

CHANGELOG_TMPL = """{version} · {date}

新增：

- 首次纳入变更记录：此前版本没有逐版记录，从本版起补齐。

文档：

- 由 `normalize.py` 生成骨架，内容待人工补齐。
"""


def die(msg: str, code: int = 2) -> int:
    print(f"❌ {msg}")
    return code


def current_group() -> str:
    try:
        r = subprocess.run(["minis-sessions-cli", "status"], capture_output=True, text=True, timeout=30)
        d = json.loads(r.stdout)
        return ((d.get("data") or {}).get("data") or {}).get("group", "") or ""
    except Exception:
        return ""


def skill_name(skill_dir: Path) -> str:
    md = skill_dir / "SKILL.md"
    if not md.is_file():
        return ""
    m = re.search(r"^name:\s*(.+)$", md.read_text(encoding="utf-8"), re.M)
    return m.group(1).strip() if m else ""


def resolve_project(arg: str) -> Path | None:
    if arg:
        p = Path(arg).expanduser().resolve()
        return p if p.is_dir() else None
    if LINK.is_file():
        p = PROJECTS / LINK.read_text(encoding="utf-8").strip()
        if p.is_dir():
            return p
    return None


def check(project: Path, check_group: bool = True) -> dict:
    """返回 {blocking:[], warnings:[], plans:[]}；blocking 非空则不改任何文件。

    check_group 只在检查"当前绑定的工程"时为 True；显式指定路径时不比对分组名，
    否则会把别的工程误判成命名不一致。
    """
    blocking, warnings, plans = [], [], []
    group = current_group() if check_group else ""
    if group and group != project.name:
        blocking.append({
            "kind": "工程名不一致",
            "group": group,
            "dir": project.name,
            "fix": f"请在 App 把会话分组名改为 {group!r}（当前目录名是 {project.name!r}）",
        })

    skills = sorted(d for d in project.iterdir() if d.is_dir() and (d / "SKILL.md").is_file())
    for s in skills:
        nm = skill_name(s)
        if nm and nm != s.name:
            blocking.append({
                "kind": "技能目录名与 name 不一致",
                "dir": s.name,
                "name": nm,
                "fix": f"把目录改名为 {nm!r}，或把 SKILL.md 的 name 改成 {s.name!r}——由你决定改哪边",
            })

    for f in PROJECT_LAYER:
        if not (project / f).is_file():
            plans.append({"action": "create", "path": f})
    if not (project / ".gitignore").is_file():
        plans.append({"action": "create", "path": ".gitignore"})
    else:
        text = (project / ".gitignore").read_text(encoding="utf-8")
        missing = [ln for ln in ignore_rules(skills) if ln and ln not in text
                   and not ln.startswith("#")]
        if missing:
            plans.append({"action": "patch_gitignore", "missing": missing})

    old, new = project / ".tmp", project / "temp"
    if old.is_dir() and new.exists():
        blocking.append({
            "kind": "临时目录冲突",
            "fix": "同时存在 .tmp/ 与 temp/，请人工合并后删掉 .tmp/ 再重跑",
        })
    elif old.is_dir():
        plans.append({"action": "rename", "src": ".tmp", "dst": "temp"})
    elif not new.exists():
        plans.append({"action": "create", "path": "temp/"})

    pm = project / "PROJECT.md"
    docs = project / "docs"
    if docs.is_dir():
        text = pm.read_text(encoding="utf-8") if pm.is_file() else ""
        for f in sorted(docs.glob("*.md")):
            if f.name not in text:
                fix = ("PROJECT.md 生成后在目录节挂引用" if not pm.is_file()
                       else "在 PROJECT.md 的目录节里挂一行引用")
                warnings.append({"kind": "docs 未引用", "file": f"docs/{f.name}", "fix": fix})

    for s in skills:
        if not (s / "CHANGELOG.md").is_file():
            plans.append({"action": "create_changelog", "skill": s.name})

    return {"project": str(project), "group": group, "skills": [s.name for s in skills],
            "blocking": blocking, "warnings": warnings, "plans": plans}


def apply(project: Path, result: dict) -> int:
    date = __import__("datetime").date.today().isoformat()
    name = project.name
    skills = result["skills"] or ["<技能名>"]
    skill = skills[0]

    for p in result["plans"]:
        act = p["action"]
        if act == "create":
            path = p["path"]
            target = project / path
            if path == "temp/":
                target.mkdir(parents=True, exist_ok=True)
                (target / ".gitkeep").touch()
                print(f"  + temp/（含 .gitkeep）")
                continue
            if target.exists():
                continue
            if path == "PROJECT.md":
                target.write_text(make_project_md(project, result["skills"]), encoding="utf-8")
            elif path == "PROGRESS.md":
                target.write_text(PROGRESS_TMPL.format(name=name, date=date), encoding="utf-8")
            elif path == ".gitignore":
                target.write_text("\n".join(ignore_rules(result["skills"])) + "\n", encoding="utf-8")
            print(f"  + {path}")
        elif act == "patch_gitignore":
            gi = project / ".gitignore"
            text = gi.read_text(encoding="utf-8").rstrip("\n")
            text += "\n" + "\n".join(p["missing"]) + "\n"
            gi.write_text(text, encoding="utf-8")
            print(f"  ~ .gitignore 追加 {len(p['missing'])} 行")
        elif act == "rename":
            (project / p["src"]).rename(project / p["dst"])
            print(f"  → {p['src']}/ 改名为 {p['dst']}/")
        elif act == "create_changelog":
            s = project / p["skill"]
            version = "1.0.0"
            md = s / "SKILL.md"
            if md.is_file():
                m = re.search(r"^version:\s*(\d+\.\d+\.\d+)", md.read_text(encoding="utf-8"), re.M)
                if m:
                    version = m.group(1)
            (s / "CHANGELOG.md").write_text(
                CHANGELOG_TMPL.format(version=version, date=date), encoding="utf-8")
            print(f"  + {p['skill']}/CHANGELOG.md")
    return 0


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    as_json = "--json" in sys.argv[1:]
    do_apply = "--apply" in sys.argv[1:]
    if len(args) > 1:
        return die("用法: normalize.py [工程目录] [--apply] [--json]", 2)

    project = resolve_project(args[0] if args else "")
    if project is None:
        return die("找不到工程目录：给一个路径，或先在会话里绑定工程", 2)

    result = check(project, check_group=not args)
    result["ok"] = not result["blocking"]

    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        print(f"检查 {project}")
        print(f"  分组：{result['group'] or '（显式路径，不比对分组名）'}")
        for b in result["blocking"]:
            print(f"  ⛔ {b['kind']}")
            for k, v in b.items():
                if k not in ("kind", "fix"):
                    print(f"     {k}：{v}")
            print(f"     {b['fix']}")
        for w in result["warnings"]:
            print(f"  ⚠ {w['kind']}：{w['file']}（{w['fix']}）")
        if result["blocking"]:
            pass  # 名字不对时不展示改造计划，避免误以为要照着做
        elif not result["plans"]:
            print("  ✓ 工程层结构已合规")
        else:
            for p in result["plans"]:
                if p["action"] == "create":
                    print(f"  · 将新建 {p['path']}")
                elif p["action"] == "rename":
                    print(f"  · 将把 {p['src']}/ 改名为 {p['dst']}/")
                elif p["action"] == "patch_gitignore":
                    print(f"  · 将向 .gitignore 追加 {len(p['missing'])} 行")
                elif p["action"] == "create_changelog":
                    print(f"  · 将为 {p['skill']} 新建 CHANGELOG.md")

    if result["blocking"]:
        print("\n⛔ 命名不一致，已停止。改完名字、迁移工程后重跑本命令。")
        return 3
    if not result["plans"]:
        return 0
    if not do_apply:
        print("\n预演结束。确认执行请加 --apply")
        return 0

    print("\n开始执行：")
    rc = apply(project, result)

    # 产出物验收：规范化完成后跑一次结构校验
    validate = Path(__file__).resolve().parent / "validate.py"
    if rc == 0 and validate.is_file():
        print("\n▶ 结构校验")
        for s in (project / p for p in result["skills"]):
            r = subprocess.run([sys.executable, str(validate), str(s)],
                               capture_output=True, text=True)
            for line in (r.stdout or "").splitlines():
                if "ERROR" in line or "WARN" in line:
                    print(f"  [{s.name}] {line.strip()}")
            print(f"  [{s.name}] {'✓ 通过' if r.returncode == 0 else '❌ 有 ERROR，需修复'}")

    print("\n完成。接下来：补 PROJECT.md 的功能点与关键决定，确认线上版本是否一致。")
    return rc


if __name__ == "__main__":
    sys.exit(main())
