#!/usr/bin/env python3
"""技能结构校验：不自动改写，只报问题。

用法:
    python3 validate.py <技能目录> [--json]
退出码: 0 无 ERROR / 1 有 ERROR / 2 用法错误
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

MAX_DESC = 200
MAX_TRIGGERS = 50
MAX_BODY_LINES = 500
DEPLOY_DIRS = (Path("/var/minis/skills"), Path("/var/minis/mounts/Minis/skills"))


def norm(s: str) -> str:
    """忽略空白与常见标点后再比较，避免标点差异造成误报。"""
    return re.sub(r"[\s，。、；：！？,.;:!?（）()「」\"']+", "", s)


def split_front(text: str):
    if not text.startswith("---"):
        return None, text
    end = text.find("\n---", 3)
    if end == -1:
        return None, text
    head = text[3:end]
    body = text[end + 4:].lstrip("\n")
    meta = {}
    for line in head.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, body


def find_git_root(start: Path) -> Path | None:
    """从 start 向上找最近的含 .git 的目录；找不到返回 None。"""
    d = start.resolve()
    while True:
        if (d / ".git").exists():
            return d
        if d == d.parent:
            return None
        d = d.parent


def git_status_short(repo: Path) -> list[str]:
    """返回 repo 下 git status --short 的行；git 不可用或出错时返回空。"""
    try:
        r = subprocess.run(["git", "-C", str(repo), "status", "--short"],
                           capture_output=True, text=True, timeout=20)
        return [l for l in r.stdout.splitlines() if l.strip()] if r.returncode == 0 else []
    except Exception:
        return []


def check(skill_dir: Path):
    errs, warns = [], []
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return [f"缺少 SKILL.md: {skill_md}"], []

    text = skill_md.read_text(encoding="utf-8")
    meta, body = split_front(text)

    if meta is None:
        errs.append("缺少 frontmatter（文件需以 --- 开头并以 --- 结尾）")
        meta = {}

    for key in ("name", "description", "version", "triggers"):
        if not meta.get(key):
            errs.append(f"frontmatter 缺少 {key}")

    name = meta.get("name", "")
    if name and name != skill_dir.name:
        errs.append(f"name ({name}) 与目录名 ({skill_dir.name}) 不一致")

    desc = meta.get("description", "")
    if desc and len(desc) > MAX_DESC:
        errs.append(f"description 过长：{len(desc)} > {MAX_DESC} 字符，会被截断")

    trig = meta.get("triggers", "")
    if trig and len(trig) > MAX_TRIGGERS:
        errs.append(f"triggers 过长：{len(trig)} > {MAX_TRIGGERS} 字符")

    # CHANGELOG.md：必带，最新版本号必须与 SKILL.md 的 version 一致
    cl = skill_dir / "CHANGELOG.md"
    if not cl.is_file():
        errs.append("缺少 CHANGELOG.md：每个版本改了什么必须随技能发布")
    else:
        cl_text = cl.read_text(encoding="utf-8")
        vers = re.findall(r"^(\d+\.\d+\.\d+)\s*·\s*(\S+)\s*$", cl_text, re.M)
        if not vers:
            errs.append("CHANGELOG.md 里没有 `x.y.z · 日期` 形式的版本行")
        else:
            nums = [v[0] for v in vers]
            if nums != sorted(nums, key=lambda s: [int(x) for x in s.split(".")], reverse=True):
                warns.append(f"CHANGELOG.md 版本未按降序排列：{', '.join(nums[:4])}")
            ver = meta.get("version", "")
            if re.fullmatch(r"\d+\.\d+\.\d+", ver) and nums[0] != ver:
                errs.append(f"CHANGELOG.md 最新版本 {nums[0]} 与 SKILL.md 的 version {ver} 不一致")
        if not re.search(r"^[-*] .+[：:]", cl_text, re.M):
            warns.append("CHANGELOG.md 没有 `- 小标题：内容` 形式的条目")

    if not re.fullmatch(r"\d+\.\d+\.\d+", meta.get("version", "")):
        warns.append(f"version 不是 x.y.z 形式：{meta.get('version')!r}")

    lines = [l for l in body.splitlines() if l.strip()]
    if len(lines) > MAX_BODY_LINES:
        errs.append(f"正文过长：{len(lines)} > {MAX_BODY_LINES} 行，细节应下沉 references/")

    if not lines:
        errs.append("正文为空")
    else:
        first = lines[0].strip()
        if first.startswith("#"):
            errs.append("正文第一句是标题；App 描述栏会显示成 Markdown 符号，应写一句话功能")
        elif desc and norm(first) != norm(desc):
            errs.append(f"正文首句与 description 不一致：\n      首句: {first}\n      描述: {desc}")

    if "## 功能" not in body:
        errs.append("缺少「## 功能」表：应列出用户能主动触发的事")

    if re.search(r"^\|\s*F\d+\s*\|", body, re.M) or re.search(r"\bF[1-9]\b", body):
        warns.append("正文出现 F1/F2 之类编号，建议去掉")

    refs = skill_dir / "references"
    if refs.is_dir() and "references/" not in body:
        warns.append("存在 references/ 但正文未指向它")

    scripts = list((skill_dir / "scripts").glob("*.py")) if (skill_dir / "scripts").is_dir() else []
    if scripts and not (skill_dir / "tests").is_dir():
        warns.append("有 scripts/ 但没有 tests/，脚本行为没有回归保护")

    # 两层目录：技能目录是内层，工程文件（PROJECT.md / PROGRESS.md）在外层。
    # 只有外层确实像工程层时才检查，避免对单独拷出来的技能误报。
    # 判据用工程文档与临时目录，不依赖 deploy.py —— 那个已经归 skill-generator 统一提供。
    parent = skill_dir.parent
    is_project_layer = ((parent / "PROJECT.md").is_file()
                        or (parent / "PROGRESS.md").is_file()
                        or (parent / "temp").is_dir()
                        or (parent / ".tmp").is_dir())

    # 工作副本本来就该在自己的 git 仓库里，deploy 会排除 .git，所以工程层下的 .git 不算问题；
    # 只有孤立的技能目录（或部署产物）带 .git 才说明仓库元数据可能被一起拷进去了。

    if is_project_layer:
        for f in ("PROJECT.md", "PROGRESS.md"):
            if not (parent / f).is_file():
                warns.append(f"工程层 {parent.name}/ 缺少 {f}：项目介绍与进度应放在技能目录的上一层")
        for f in ("PROJECT.md", "PROGRESS.md", "WORKFLOW.md", "deploy.py"):
            if (skill_dir / f).exists():
                warns.append(f"技能目录里不应有 {f}：那是工程层文件，放上一层")
        docs = parent / "docs"
        if docs.is_dir():
            pm = parent / "PROJECT.md"
            ptxt = pm.read_text(encoding="utf-8") if pm.is_file() else ""
            for f in sorted(docs.glob("*.md")):
                if f.name not in ptxt:
                    warns.append(f"docs/{f.name} 未在 PROJECT.md 里引用：沉淀下来的调研要能从工程介绍找到")

    # ---- 版本控制 ----
    # 部署产物（/var/minis/skills/ 与镜像）不需要版本控制，也不该有 .git/.gitignore；
    # 只有工作副本才要求 git。按路径判断，不靠"上层是不是工程层"。
    resolved = skill_dir.resolve()
    is_deploy = any(resolved == d or d in resolved.parents for d in DEPLOY_DIRS)

    if is_deploy:
        for name in (".git", ".gitignore"):
            if (skill_dir / name).exists():
                errs.append(f"部署产物里不应有 {name}：deploy 时要排除")
        git_root = None
    else:
        git_root = find_git_root(skill_dir)
    if not is_deploy:
        if git_root is None:
            errs.append("技能目录不在任何 git 仓库里：改动无法追溯，也无法回滚。请先 git init 并提交。")
        else:
            dirty = git_status_short(git_root)
            if dirty and not os.environ.get("VALIDATE_ALLOW_DIRTY"):
                warns.append(
                    "所在仓库有未提交改动（%d 项）：发布前应提交完，否则线上产物没有对应的提交记录"
                    % len(dirty))

    # ---- 工程层与技能层的忽略边界 ----
    if is_project_layer:
        try:
            r = subprocess.run(["git", "-C", str(parent), "check-ignore", "-q", skill_dir.name],
                               capture_output=True, text=True, timeout=20)
            if r.returncode != 0:
                warns.append(
                    f"技能目录 {skill_dir.name}/ 没有被工程仓库忽略："
                    "工程仓库的 .gitignore 里应有 /" + skill_dir.name + "/")
        except Exception:
            pass

    # 供下面几条判定用：功能表的行、正文各 ## 小节
    func_table_rows = []
    m = re.search(r"^##\s*功能.*$", body, re.M)
    if m:
        rest = body[m.end():]
        nxt = re.search(r"^##\s", rest, re.M)
        seg = rest[:nxt.start()] if nxt else rest
        for line in seg.splitlines():
            s = line.strip()
            if s.startswith("|") and not re.fullmatch(r"\|[\s:|-]+\|", s):
                func_table_rows.append(s)

    func_sections = []
    for mm in re.finditer(r"^##\s+(.+)$", body, re.M):
        title = mm.group(1).strip()
        start = mm.end()
        nxt = re.search(r"^##\s", body[start:], re.M)
        end = start + nxt.start() if nxt else len(body)
        func_sections.append((title, body[start:end]))

    # --- 可从文件内容判定的规则（原来写在 checklist 里靠人看的） ---
    desc = meta.get("description", "")

    # 1) description 应是功能名列举：逗号分隔、2 项以上、每项不长
    parts = [x.strip() for x in re.split(r"[，,]", desc) if x.strip()]
    if len(parts) < 2:
        warns.append("description 看起来不是功能名列举：用「绑定，迁移，查询」这种逗号分隔的短语")
    elif any(len(x) > 12 for x in parts):
        warns.append("description 里有超过 12 字的项，可能写成了长句")

    # 2) triggers 不应该是技术词
    trig = meta.get("triggers", "")
    if re.search(r"--[a-z]|[a-z]+_[a-z]+|[a-z]+\([^)]*\)", trig):
        warns.append("triggers 里有命令或函数名：用户不会这样说话")

    # 3) 功能表里不该出现参数与编号
    func_names = []
    for r in func_table_rows[:20]:
        cells = [c.strip() for c in r.strip("|").split("|")]
        if not cells or not cells[0]:
            continue
        head = cells[0]
        if head in ("功能", "---") or set(head) <= {"-", ":", " "}:
            continue
        func_names.append(head)
        if re.search(r"--[a-z]|`|^F\d|\bF\d\b", head):
            warns.append(f"功能表的功能名像参数或编号，用户不会这样说：{head[:30]}")

    # 4) 每个功能小节里应有代码块（命令或者示例）
    for fname in func_names:
        hit = next((b for n, b in func_sections if n == fname), None)
        if hit is not None and "```" not in hit:
            warns.append(f"功能「{fname}」小节里没有代码块：读者不知道要跑什么")

    # 5) 脚本目录：多个 .py 就看是否各司其职
    sc = skill_dir / "scripts"
    if sc.is_dir():
        scripts = sorted(p.name for p in sc.glob("*.py"))
        if len(scripts) > 5:
            warns.append(f"scripts/ 下有 {len(scripts)} 个脚本，确认它们是按职责分文件而不是重复")

    # 6) 破坏性操作必须有 --dry
    for py in (sc.glob("*.py") if sc.is_dir() else []):
        try:
            src = norm(py.read_text())
        except Exception:
            continue
        risky = re.search(r"--(apply|force)", src)
        if risky and "--dry" not in src and "预演" not in src:
            warns.append(f"{py.name} 里有 --apply 但没看到 --dry 或预演：用户没法先看计划")

    # 7) 没有预建空 assets/
    at = skill_dir / "assets"
    if at.is_dir() and not any(at.iterdir()):
        warns.append("assets/ 是空目录：用不到就不该建，要么放内容要么删掉")

    # 8) 工程层不该有 deploy.py / WORKFLOW.md（技能目录外一层）
    layer = skill_dir.parent
    if (layer / "PROJECT.md").exists() or (layer / "PROGRESS.md").exists():
        for f in ("deploy.py", "WORKFLOW.md"):
            if (layer / f).exists():
                warns.append(f"工程层不该有 {f}：工具与流程都由 skill-generator 统一提供")

    return errs, warns


def main() -> int:
    raw = sys.argv[1:]
    args = [a for a in raw if not a.startswith("--")]
    as_json = "--json" in raw
    allow_dirty = "--allow-dirty" in raw
    if allow_dirty:
        os.environ["VALIDATE_ALLOW_DIRTY"] = "1"
    if len(args) != 1:
        print("用法: python3 validate.py <技能目录> [--json] [--allow-dirty]")
        return 2
    d = Path(args[0]).expanduser().resolve()
    if not d.is_dir():
        print(f"❌ 目录不存在: {d}")
        return 2

    errs, warns = check(d)
    if as_json:
        print(json.dumps({"skill": d.name, "errors": errs, "warnings": warns,
                          "ok": not errs}, ensure_ascii=False, indent=1))
    else:
        print(f"检查 {d}")
        for e in errs:
            print(f"  ERROR {e}")
        for w in warns:
            print(f"  WARN  {w}")
        print(f"{len(errs)} 个 ERROR，{len(warns)} 个 WARN")
    return 0 if not errs else 1


if __name__ == "__main__":
    sys.exit(main())
