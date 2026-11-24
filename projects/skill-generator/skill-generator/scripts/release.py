#!/usr/bin/env python3
"""发布流程：status / prepare / confirm / restore。

把「确认包一致 → 提交 → 部署」这条链交给代码，代替原来一百多行文字规则。

用法:
    python3 release.py status
    python3 release.py prepare <技能名>
    python3 release.py confirm <hash>
    python3 release.py restore

退出码:
    0 成功
    1 检查未通过 / 发布失败
    2 用法错误
    3 hash 不一致（内容变过，需重新 prepare）

约定:
    - 工程根默认当前目录，可用 --project 指定。
    - pending 文件写在工程层 temp/.release-pending.json。
    - 确认包贴出后任何文件变动都会让 hash 变，confirm 直接拒绝。
      hash 不是授权凭据（重新 prepare 能拿到新 hash），它只保证
      「你看到的清单」与「即将提交的内容」是同一份。
"""
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VALIDATE = HERE / "validate.py"
DEPLOY = HERE / "deploy.py"
MOUNT = Path("/var/minis/mounts/Minis")
SKILLS_DIR = MOUNT / "skills"
DIST_DIR = MOUNT / "skills-dist"

TYPES = {"feat", "fix", "docs", "test", "chore", "refactor", "perf"}


def sh(cmd, cwd=None):
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None,
                          capture_output=True, text=True)


def die(msg: str, rc: int = 2):
    print(f"❌ {msg}")
    return rc


def project_root(argv):
    for i, a in enumerate(argv):
        if a == "--project" and i + 1 < len(argv):
            return Path(argv[i + 1]).expanduser().resolve()
        if a.startswith("--project="):
            return Path(a.split("=", 1)[1]).expanduser().resolve()
    return Path.cwd().resolve()


def skill_dirs(root: Path):
    """工程层下所有含 SKILL.md 的子目录。"""
    return sorted(p for p in root.iterdir()
                  if p.is_dir() and (p / "SKILL.md").is_file()
                  and not p.name.startswith("."))


def is_project(root: Path) -> bool:
    if (root / "PROJECT.md").exists() or (root / "PROGRESS.md").exists():
        return True
    return bool(skill_dirs(root))


def git(root: Path, *args):
    return sh(["git", *args], cwd=root)


def changes(root: Path):
    """返回 [(状态码, 相对路径)]，用于算 hash 与列清单。"""
    if not (root / ".git").exists() and not git(root, "rev-parse", "--git-dir").returncode == 0:
        return []
    out = git(root, "status", "--porcelain")
    if out.returncode != 0:
        return []
    items = []
    for line in out.stdout.splitlines():
        if not line.strip():
            continue
        code, path = line[:2].strip(), line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        items.append((code, path))
    return items


def snapshot(root: Path, skills):
    """对将要提交的内容算 sha256：路径 + 文件字节。

    覆盖技能仓库与工程仓库两处；未跟踪文件也算，因为发布时会被一起提交。
    """
    h = hashlib.sha256()
    repos = [root] + [root / s for s in skills]
    for repo in repos:
        if not repo.is_dir():
            continue
        tag = repo.name if repo != root else "<project>"
        h.update(f"REPO:{tag}\n".encode())
        for code, rel in sorted(changes(repo)):
            if rel.endswith(".release-pending.json"):
                continue
            f = repo / rel
            h.update(f"{code} {rel}\n".encode())
            if f.is_file():
                h.update(f.read_bytes())
            elif f.is_dir():
                for sub in sorted(f.rglob("*")):
                    if sub.is_file():
                        h.update(str(sub.relative_to(repo)).encode())
                        h.update(sub.read_bytes())
    return h.hexdigest()[:16]


def ignore_it(root: Path, pattern: str):
    """写进 .git/info/exclude：本地生效，不改仓库里的 .gitignore。"""
    info = root / ".git" / "info"
    if not info.is_dir():
        return
    ex = info / "exclude"
    old = ex.read_text() if ex.exists() else ""
    if pattern not in old.splitlines():
        ex.write_text(old.rstrip("\n") + "\n" + pattern + "\n")


def version_of(skill: Path):
    md = (skill / "SKILL.md").read_text(encoding="utf-8")
    m = re.search(r"^version:\s*(\S+)", md, re.M)
    return m.group(1) if m else None


def changelog_top(skill: Path, ver):
    """取变更记录里该版本的条目行。"""
    cl = skill / "CHANGELOG.md"
    if not cl.is_file():
        return []
    lines = cl.read_text(encoding="utf-8").splitlines()
    out, on = [], False
    for line in lines:
        if re.fullmatch(rf"{re.escape(ver)}\s*·\s*\d{{4}}-\d{{2}}-\d{{2}}", line.strip()):
            on = True
            out.append(line.strip())
            continue
        if on and re.fullmatch(r"\d+\.\d+\.\d+\s*·.*", line.strip()):
            break
        if on:
            out.append(line)
    return out


def numstat(repo: Path):
    """每个文件的 +x −y。返回 {路径: (加, 删)}。"""
    res = {}
    out = git(repo, "diff", "--numstat", "HEAD")
    if out.returncode == 0:
        for line in out.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) == 3:
                a, d, p = parts
                res[p] = (a if a != "-" else "?", d if d != "-" else "?")
    return res


def untracked(repo: Path):
    out = git(repo, "ls-files", "--others", "--exclude-standard")
    return [l for l in out.stdout.splitlines() if l.strip()]


def stage_of(root: Path, skills):
    dirty = sum(len(changes(root)) for _ in [0]) + sum(
        len(changes(root / s)) for s in skills)
    pending = (root / "temp" / ".release-pending.json")
    if dirty and pending.exists():
        return "待发布（已出确认包，内容可能有变）"
    if dirty:
        return "改中（有未提交改动）"
    return "已同步"


def cmd_status(root: Path) -> int:
    skills = skill_dirs(root)
    print(f"工程：{root}")
    print(f"阶段：{stage_of(root, [s.name for s in skills])}")
    print()
    if not skills:
        print("  ⚠️ 没有含 SKILL.md 的子目录，不像工程目录")
    for s in skills:
        ver = version_of(s)
        app = Path("/var/minis/skills") / s.name / "SKILL.md"
        mir = SKILLS_DIR / s.name / "SKILL.md"
        av = re.search(r"^version:\s*(\S+)", app.read_text(encoding="utf-8"), re.M).group(1) \
            if app.is_file() else "未部署"
        mv = re.search(r"^version:\s*(\S+)", mir.read_text(encoding="utf-8"), re.M).group(1) \
            if mir.is_file() else "未部署"
        same = "✅" if ver == av == mv else "⚠️"
        print(f"  {s.name}")
        print(f"    工作副本 {ver} ｜ 权威源 {av} ｜ 镜像 {mv}  {same}")
        d = changes(s)
        if d:
            print(f"    未提交 {len(d)} 项")
    pd = changes(root)
    print(f"  工程仓库：{'未提交 ' + str(len(pd)) + ' 项' if pd else '干净'}")
    pend = root / "temp" / ".release-pending.json"
    if pend.exists():
        try:
            p = json.loads(pend.read_text())
            print(f"  待确认：{p.get('hash')}（{p.get('at')}，技能 {', '.join(p.get('skills', []))}）")
        except Exception:
            pass
    return 0


def cmd_prepare(root: Path, names) -> int:
    skills = skill_dirs(root)
    if not skills:
        return die("这个目录下没有含 SKILL.md 的技能目录", 2)
    picked = [s for s in skills if s.name in names] if names else []
    if not picked:
        print("请指定要发布的技能名（可多个）：")
        for s in skills:
            print(f"  {s.name}  v{version_of(s)}")
        return 2

    h = snapshot(root, [s.name for s in picked])
    blocks, total_a, total_d, total_n = [], 0, 0, 0

    for s in picked:
        ver = version_of(s)
        print(f"▶ {s.name}  v{ver}")
        entry = changelog_top(s, ver)
        if entry:
            blocks.append("\n".join(entry))
        print()
        rows = []
        ns = numstat(s)
        for path, (a, d) in sorted(ns.items()):
            rows.append((path, "改", a, d))
            if str(a).isdigit():
                total_a += int(a)
            if str(d).isdigit():
                total_d += int(d)
            total_n += 1
        for path in untracked(s):
            n = len((s / path).read_bytes().splitlines()) if (s / path).is_file() else 0
            rows.append((path, "增", str(n), "0"))
            total_a += n
            total_n += 1
        width = max([len(r[0]) for r in rows], default=10)
        for path, kind, a, d in rows:
            print(f"  {kind}  {path.ljust(width)}  +{a} −{d}")
        print(f"  合计 {len(rows)} 个文件  +{total_a} −{total_d}")
        print()

    # 工程仓库的改动也列出来（PROGRESS.md 等）
    pd = changes(root)
    if pd:
        print("工程仓库改动：")
        for code, path in pd:
            print(f"  {code}  {path}")
        print()

    (root / "temp").mkdir(exist_ok=True)
    ignore_it(root, "temp/.release-pending.json")
    pend = root / "temp" / ".release-pending.json"
    pend.write_text(json.dumps({
        "hash": h, "skills": [s.name for s in picked],
        "at": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }, ensure_ascii=False, indent=1))

    if total_n == 0:
        print("❌ 没有待提交的改动：改完再 prepare，或先确认工作区是否已经提交")
        return 2

    print("=" * 60)
    print("确认包（贴到对话里给用户看）：")
    print("-" * 60)
    for b in blocks:
        print(b)
        print()
    print(f"文件：{total_n} 个，+{total_a} −{total_d}")
    print(f"snapshot：{h}")
    print("-" * 60)
    print(f"用户确认后执行：python3 {Path(__file__).name} confirm {h}")
    return 0


def cmd_confirm(root: Path, given: str) -> int:
    pend = root / "temp" / ".release-pending.json"
    if not pend.exists():
        return die("没有待发布的确认包：先跑 prepare", 2)
    try:
        p = json.loads(pend.read_text())
    except Exception:
        return die("确认包文件损坏：重新 prepare", 2)

    names = p.get("skills", [])
    cur = snapshot(root, names)
    if cur != given or cur != p.get("hash"):
        print("❌ 内容与确认包不一致，拒绝发布")
        print(f"   确认包里 {p.get('hash')} ｜ 你给的 {given} ｜ 现在是 {cur}")
        print("   贴出确认包之后有文件变动。重新 prepare，把新包贴给用户再确认。")
        return 3

    skills = [root / n for n in names]
    for s in skills:
        # 1) 结构校验（发布阶段就是要脏，显式允许）
        r = sh([sys.executable, str(VALIDATE), str(s), "--allow-dirty"])
        print(r.stdout.rstrip())
        if r.returncode != 0:
            print(f"  ❌ {s.name} 结构校验未通过，拒绝上线")
            return 1
        # 2) 回归测试
        run = s / "tests" / "run.py"
        if run.is_file():
            r = sh([sys.executable, str(run)], cwd=s)
            tail = [l for l in r.stdout.splitlines() if l.strip()][-1:]
            print(f"  测试：{tail[0] if tail else '(无输出)'}")
            bad = re.search(r"失败\s*([1-9]\d*)\s*项", r.stdout)
            if r.returncode != 0 or bad:
                print(f"  ❌ {s.name} 测试未通过，拒绝上线")
                return 1
        else:
            print("  ⚠️ 没有 tests/run.py，未做回归保护")

    ver = ", ".join(f"{s.name} v{version_of(s)}" for s in skills)
    # 3) 提交：技能仓库 → 工程仓库
    for s in skills:
        r = git(s, "add", "-A")
        msg = f"release({s.name}): v{version_of(s)}"
        r = git(s, "commit", "-m", msg)
        head = git(s, "log", "--oneline", "-1").stdout.strip()
        print(f"  提交：{head}" if r.returncode == 0 else f"  （{s.name} 没有可提交内容）")

    # 4) 部署 + 打包
    r = sh([sys.executable, str(DEPLOY)], cwd=str(root))
    print(r.stdout.rstrip())
    if r.returncode != 0:
        print("  ❌ 部署失败")
        return 1

    r = git(root, "add", "-A")
    r = git(root, "commit", "-m", f"docs(progress): 记录 {ver} 上线")
    if r.returncode == 0:
        print(f"  提交：{git(root, 'log', '--oneline', '-1').stdout.strip()}")

    pend.unlink(missing_ok=True)

    print()
    print("=" * 60)
    print("发布完成")
    for s in skills:
        app = Path("/var/minis/skills") / s.name / "SKILL.md"
        mir = SKILLS_DIR / s.name / "SKILL.md"
        av = re.search(r"^version:\s*(\S+)", app.read_text(encoding="utf-8"), re.M).group(1) if app.is_file() else "—"
        mv = re.search(r"^version:\s*(\S+)", mir.read_text(encoding="utf-8"), re.M).group(1) if mir.is_file() else "—"
        print(f"  {s.name}：工作副本 {version_of(s)} ｜ 权威源 {av} ｜ 镜像 {mv}")
    names = {s.name for s in skills}
    for z in sorted(DIST_DIR.glob("*.zip")):
        if any(z.name.startswith(n + "_v") for n in names):
            print(f"  产物：{z.name}（{max(1, z.stat().st_size // 1024)} KB）")
    arch = DIST_DIR / "archive"
    for n in sorted(names):
        old_zips = sorted((arch / n).glob("*.zip")) if (arch / n).is_dir() else []
        for a in old_zips[-3:]:
            print(f"  归档：{a.relative_to(DIST_DIR)}")
    return 0


RESTORE = """撤销 / 回滚：提交与线上都退回上一版，改动全部保留。

# 1) 记现场
cd "{root}"
git log --oneline -3          # 确认 <上次提交> 是哪一个
git status --short            # 记下改动清单

# 2) 提交退回，改动保留
cd "{skill}"
git reset --soft <上次提交>
git reset -q
git status --short            # 改动必须还在

# 3) 导出旧版并核对
rm -rf /tmp/prev && mkdir -p /tmp/prev
git archive HEAD | tar -x -C /tmp/prev
grep -m1 '^version' /tmp/prev/SKILL.md    # 应为旧版本号

# 4) 备份线上，用旧版覆盖
rm -rf /tmp/now && cp -a /var/minis/skills/{name} /tmp/now
rm -rf /var/minis/skills/{name}
cp -a /tmp/prev /var/minis/skills/{name}

# 5) 同步镜像
python3 /var/minis/skills/project-workspace/scripts/ws.py sync --push

# 6) 核对：前两个是旧版，第三个是新版（工作区）
grep -m1 '^version' /var/minis/skills/{name}/SKILL.md
grep -m1 '^version' /var/minis/mounts/Minis/skills/{name}/SKILL.md
grep -m1 '^version' "{skill}/SKILL.md"

禁止：git reset --hard、git checkout -- .、用 git revert 代替、直接删线上目录。
"""


def cmd_restore(root: Path) -> int:
    skills = skill_dirs(root)
    if not skills:
        return die("没有技能目录", 2)
    s = skills[0]
    print(RESTORE.format(root=root, skill=s, name=s.name))
    print("（以上为打印步骤，不自动执行——撤销出错代价高于手打）")
    return 0


def main() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    root = project_root(argv)
    if not is_project(root):
        return die(f"这不像工程目录（没有含 SKILL.md 的子目录）: {root}\n"
                   "   请在工程目录下执行，或用 --project 指定工程根。", 2)

    cmd = argv[0]
    rest = [a for a in argv[1:] if not a.startswith("--pr") and a != "--project"]
    if cmd == "status":
        return cmd_status(root)
    if cmd == "prepare":
        return cmd_prepare(root, rest)
    if cmd == "confirm":
        if not rest:
            return die("需要 hash：python3 release.py confirm <hash>", 2)
        return cmd_confirm(root, rest[0])
    if cmd == "restore":
        return cmd_restore(root)
    return die(f"未知子命令：{cmd}（status / prepare / confirm / restore）", 2)


if __name__ == "__main__":
    sys.exit(main())