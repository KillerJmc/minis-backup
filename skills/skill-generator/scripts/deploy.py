#!/usr/bin/env python3
"""把工程里的技能工作副本上线到 skills，并生成发布产物。

用法（在工程目录下执行，默认处理当前目录）：
    python3 deploy.py                       # 全部技能：测 → 同步 → 推镜像 → 打包
    python3 deploy.py <技能名>              # 只上线指定技能
    python3 deploy.py --dry                 # 只显示差异与将要做的事
    python3 deploy.py --skip-test           # 跳过测试（仅本地排查用）
    python3 deploy.py --pack-only [技能名]  # 只打包，不部署
    python3 deploy.py --project <工程目录>   # 指定工程根（默认取当前目录）

两个触发点，逻辑相同：
    1. 自动：发布流程的第二轮，确认变更记录之后由技能执行；
    2. 手动：用户说「发布 <技能名>」或直接跑本脚本。

工程目录下的每个子目录，只要有 SKILL.md，就视为一个技能的工作副本。

产物规则：
    /var/minis/mounts/Minis/skills-dist/<技能名>_v<版本>.zip   ← 只留最新一版
    /var/minis/mounts/Minis/skills-dist/archive/<技能名>/<技能名>_v<旧版本>.zip
    顺序：先写新包（原子落盘），成功后才挪走旧版；打包失败则什么都不动。
"""
import filecmp
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

DEFAULT_ROOT = Path.cwd()          # 默认：当前工作目录就是工程根
ROOT: Path                          # 由 --project 或 cwd 决定，见 main()
SKILLS_DIR = Path("/var/minis/skills")
SYNC = Path("/var/minis/skills/project-workspace/scripts/ws.py")
MOUNT = Path("/var/minis/mounts/Minis")
MIRROR_DIR = MOUNT / "skills"
DIST_DIR = MOUNT / "skills-dist"
ARCHIVE_DIR = DIST_DIR / "archive"
VALIDATE = Path(__file__).resolve().parent / "validate.py"
SKIP = {".git", ".gitignore", "__pycache__", ".DS_Store", "report.md"}


def require_mount() -> bool:
    """挂载根不存在时，任何功能都不该继续：直接引导用户去挂载。"""
    if MOUNT.is_dir():
        return True
    print(f"❌ 外部挂载不存在：{MOUNT}")
    print("   本工具的所有产物（镜像、skills-dist、archive）都在挂载目录下，没有挂载就无处存放。")
    print("   请先挂载外部文件夹：设置 → 挂载外部文件夹（minis://settings/mount-external）")
    print("   挂载后确认路径为 /var/minis/mounts/Minis，再重跑本命令。")
    return False


def skills() -> list[Path]:
    return sorted(d for d in ROOT.iterdir() if d.is_dir() and (d / "SKILL.md").is_file())


def rel_files(base: Path) -> set[Path]:
    return {p.relative_to(base) for p in base.rglob("*")
            if p.is_file() and not any(part in SKIP for part in p.parts)}


def read_version(skill_dir: Path) -> str:
    md = skill_dir / "SKILL.md"
    if not md.is_file():
        return ""
    m = re.search(r"^version:\s*(\S+)", md.read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else ""


def pack_dist(name: str, dry: bool) -> bool:
    """从挂载镜像打包到 skills-dist，成功后再把旧版挪进 archive。失败不影响上线结果。"""
    if not require_mount():
        return True
    src = MIRROR_DIR / name
    if not src.is_dir():
        print(f"  ⚠️ 镜像目录不存在，跳过打包: {src}")
        return True
    version = read_version(src)
    if not version:
        print(f"  ⚠️ 读不到 version，跳过打包: {src}/SKILL.md")
        return True

    out = DIST_DIR / f"{name}_v{version}.zip"
    olds = sorted(p for p in DIST_DIR.glob(f"{name}_v*.zip") if p.name != out.name) \
        if DIST_DIR.is_dir() else []
    files = [p for p in sorted(src.rglob("*"))
             if p.is_file() and not any(part in SKIP for part in p.relative_to(src).parts)]

    if dry:
        print(f"  · 将生成 {out}（{len(files)} 个文件）")
        if olds:
            print(f"  · 将把 {len(olds)} 个旧版挪到 {ARCHIVE_DIR / name}/")
        return True

    # 1) 先写新包：临时名 + 原子改名，失败时旧包一个不动
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".zip.tmp")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for p in files:
                z.write(p, f"{name}/{p.relative_to(src)}")
        if not tmp.is_file() or tmp.stat().st_size == 0:
            raise OSError("生成的文件为空")
        os.replace(tmp, out)
    except (OSError, zipfile.BadZipFile) as e:
        tmp.unlink(missing_ok=True)
        print(f"  ⚠️ 打包失败（旧产物未动，不影响上线）: {e}")
        return True
    print(f"  ✓ 产物 {out.name}（{len(files)} 个文件，{out.stat().st_size // 1024} KB）")

    # 2) 新包已就位，才归档旧版
    if olds:
        dest = ARCHIVE_DIR / name
        try:
            dest.mkdir(parents=True, exist_ok=True)
            moved = 0
            for p in olds:
                os.replace(p, dest / p.name)
                moved += 1
            print(f"  ✓ 归档 {moved} 个旧版 → {dest}")
        except OSError as e:
            print(f"  ⚠️ 归档失败（新产物已在位，旧版留在 skills-dist）: {e}")

    # 3) 归档区只留里程碑版（x.y.0），补丁版归档后即删——规则见 git-workflow.md
    prune_archive(name)
    return True


def prune_archive(name: str) -> None:
    """归档区每个 x.y 只留最高补丁版。本次发布的版本不在归档区，天然不参与。"""
    dest = ARCHIVE_DIR / name
    if not dest.is_dir():
        return
    groups = {}
    for z in dest.glob(f"{name}_v*.zip"):
        m = re.search(r"_v(\d+)\.(\d+)\.(\d+)\.zip$", z.name)
        if m:
            key = (int(m.group(1)), int(m.group(2)))
            groups.setdefault(key, []).append((int(m.group(3)), z))
    removed = []
    for items in groups.values():
        items.sort()
        for _, z in items[:-1]:
            z.unlink(missing_ok=True)
            removed.append(z.name)
    if removed:
        print(f"  · 归档区清理 {len(removed)} 个非最高补丁版：{', '.join(removed)}")


def deploy_one(src: Path, dry: bool, skip_test: bool) -> bool:
    name = src.name
    dst = SKILLS_DIR / name
    print(f"\n▶ {name}")

    # 先跑结构校验：ERROR 直接拒绝上线，WARN 打印但不阻塞
    if VALIDATE.is_file():
        r = subprocess.run([sys.executable, str(VALIDATE), str(src)],
                           capture_output=True, text=True)
        out = (r.stdout or "").strip()
        for line in out.splitlines():
            if "ERROR" in line or "WARN" in line:
                print("  " + line.strip())
        if r.returncode != 0:
            print("  ❌ 结构校验未通过，拒绝上线")
            return False
        print("  ✓ 结构校验通过")

    tests = src / "tests" / "run.py"
    if tests.is_file() and not skip_test:
        r = subprocess.run([sys.executable, str(tests)], capture_output=True, text=True)
        tail = (r.stdout or "").strip().splitlines()[-1:] or ["(无输出)"]
        print("  " + tail[0])
        if r.returncode != 0:
            print("  ❌ 测试未通过，拒绝上线")
            print((r.stdout or "")[-1200:])
            return False
    elif not tests.is_file():
        print("  ⚠️ 没有 tests/run.py，未做回归保护")

    have = rel_files(src)
    want = rel_files(dst) if dst.is_dir() else set()
    changed = sorted(p for p in have if not (dst / p).is_file()
                     or not filecmp.cmp(src / p, dst / p, shallow=False))
    removed = sorted(want - have)
    for p in changed:
        print(f"  → {p}")
    for p in removed:
        print(f"  ✕ {p}（产物多余，将删除）")
    if not changed and not removed:
        print("  ✓ 无差异")
        return True
    if dry:
        return True

    for p in changed:
        (dst / p).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / p, dst / p)
    for p in removed:
        (dst / p).unlink(missing_ok=True)
    # 删文件后可能留下空目录，从深到浅清理
    for d in sorted({(dst / p).parent for p in removed}, key=lambda x: -len(x.parts)):
        if d != dst and d.is_dir() and not any(d.iterdir()):
            d.rmdir()
            print(f"  ✕ {d.relative_to(dst)}/（空目录，已清理）")
    print(f"  ✓ 已上线 {len(changed)} 个文件" + (f"，删除 {len(removed)} 个" if removed else ""))
    return True


def main() -> int:
    global ROOT
    argv = sys.argv[1:]
    dry = "--dry" in argv
    skip_test = "--skip-test" in argv
    pack_only = "--pack-only" in argv

    if "--project" in argv:
        i = argv.index("--project")
        if i + 1 >= len(argv):
            print("❌ --project 后面要跟工程目录")
            return 2
        ROOT = Path(argv[i + 1]).expanduser().resolve()
        argv = argv[:i] + argv[i + 2:]
    else:
        ROOT = DEFAULT_ROOT

    only = [a for a in argv if not a.startswith("--")]

    if not ROOT.is_dir():
        print(f"❌ 工程目录不存在: {ROOT}")
        return 2

    if not require_mount():
        return 2

    targets = skills()
    if not targets:
        print(f"❌ 这不像工程目录（没有含 SKILL.md 的子目录）: {ROOT}")
        print("   请在工程目录下执行，或用 --project 指定工程根。")
        return 2
    if only:
        names = {d.name for d in targets}
        missing = [n for n in only if n not in names]
        if missing:
            print(f"❌ 工程里没有这些技能: {', '.join(missing)}")
            return 2
        targets = [d for d in targets if d.name in only]
    if not targets:
        print("❌ 工程里没有找到任何技能（子目录缺 SKILL.md）")
        return 1

    if pack_only:
        print("▶ 只打包（从挂载镜像取源）")
        for d in targets:
            pack_dist(d.name, dry)
        return 0

    ok = all(deploy_one(d, dry, skip_test) for d in targets)
    if not ok:
        return 1
    if dry:
        print("\n（预演结束，未改动磁盘）")
        print("\n▶ 产物（预演）")
        for d in targets:
            pack_dist(d.name, True)
        return 0

    if SYNC.is_file():
        r = subprocess.run([sys.executable, str(SYNC), "sync", "--push"],
                           capture_output=True, text=True)
        print("\n✓ 已推送到外部镜像" if r.returncode == 0 else f"⚠️ 镜像同步失败: {r.stdout}{r.stderr}")
    else:
        print("\n⚠️ 没有 project-workspace 的 ws.py，跳过镜像同步")

    print("\n▶ 打包发布产物")
    for d in targets:
        pack_dist(d.name, False)
    return 0


if __name__ == "__main__":
    sys.exit(main())