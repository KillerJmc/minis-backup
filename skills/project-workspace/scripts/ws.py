#!/usr/bin/env python3
"""Minis 外部挂载工作区工具。

子命令：
  auto [--json]             会话开场：分组名 ↔ 工程目录，建/关联并列出目录内容
  bootstrap [--json]        发现挂载、准备 projects/ 与 skills/、报告状态
  sync [--dry] [--push|--pull] [技能名]
                            技能 + 记忆双向同步（默认只补缺失，记忆按 mtime 取新）
  list                      列出工程
  new <名字>                新建工程并关联当前 chat
  link <名字>               关联已有工程
  which                     当前 chat 关联的工程
  migrate [旧 新] [--dry]    零参数=按当前分组自动推断改名
                            改名/合并工程目录；目标已存在则合并，有冲突整体中止

退出码：0 正常 / 3 没有外部挂载 / 4 未关联工程
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# 路径可被环境变量覆盖，便于沙箱测试（WS_MOUNTS / WS_APP_SKILLS / WS_APP_MEMORY / WS_LINK_FILE）
MOUNTS = Path(os.environ.get("WS_MOUNTS", "/var/minis/mounts"))
APP_SKILLS = Path(os.environ.get("WS_APP_SKILLS", "/var/minis/skills"))
APP_MEMORY = Path(os.environ.get("WS_APP_MEMORY", "/var/minis/memory"))
LINK_FILE = Path(os.environ.get("WS_LINK_FILE", "/var/minis/workspace/.project"))
PREV_FILE = Path(os.environ.get("WS_PREV_FILE", str(LINK_FILE.parent / ".project-prev")))


ERR_MSG = ""


def ensure_dir(p: Path) -> bool:
    """安全建目录：被文件占据或权限不足时返回 False 并记下原因。"""
    global ERR_MSG
    if p.is_dir():
        return True
    if p.exists():
        ERR_MSG = f"❌ 路径被文件占据，无法创建目录: {p}"
        return False
    try:
        p.mkdir(parents=True, exist_ok=True)
        return True
    except OSError as e:
        ERR_MSG = f"❌ 无法创建目录 {p}: {e}"
        return False


def find_mount() -> Path | None:
    if not MOUNTS.is_dir():
        return None
    dirs = [d for d in MOUNTS.iterdir() if d.is_dir()]
    for d in dirs:
        if d.name.lower() == "minis":
            return d
    return dirs[0] if len(dirs) == 1 else None


def valid_name(name: str) -> bool:
    """工程名只允许单层、非隐藏、不含路径分隔符。"""
    if not name or name in (".", "..") or name.startswith(".") or name.startswith("-"):
        return False
    if "/" in name or "\\" in name or "\0" in name:
        return False
    return Path(name).name == name


def dirs_in(p: Path) -> list[str]:
    return sorted(d.name for d in p.iterdir() if d.is_dir()) if p.is_dir() else []


def missing_both_ways(mount: Path) -> tuple[list[str], list[str]]:
    ext = mount / "skills"
    app = set(dirs_in(APP_SKILLS))
    out = set(dirs_in(ext))
    return sorted(app - out), sorted(out - app)  # app→ext, ext→app


def cmd_bootstrap(args: list[str]) -> int:
    as_json = "--json" in args
    mount = find_mount()
    if mount is None:
        if as_json:
            print(json.dumps({"mount": None, "reason": "no-mount"}))
        else:
            print("❌ 没有找到外部挂载")
        return 3

    projects, skills = mount / "projects", mount / "skills"
    created = []
    for d in (projects, skills):
        if not d.is_dir():
            if not ensure_dir(d):
                print(ERR_MSG, file=sys.stderr if as_json else sys.stdout)
                return 1
            created.append(str(d))
            if not as_json:
                print(f"＋ 已创建 {d}")

    to_ext, to_app = missing_both_ways(mount)
    data = {
        "mount": str(mount),
        "projects": dirs_in(projects),
        "skills_missing_external": to_ext,
        "skills_missing_app": to_app,
        "created": created,
    }
    if as_json:
        print(json.dumps(data, ensure_ascii=False))
        return 0

    print(f"✅ 挂载: {mount}")
    print(f"   projects: {projects}")
    print(f"   skills:   {skills}")
    print("\n现有工程:" + ("" if data["projects"] else " （空）"))
    for p in data["projects"]:
        print(f"  - {p}")
    if to_ext:
        print(f"\n需同步到外部: {', '.join(to_ext)}")
    if to_app:
        print(f"\n需同步到 app : {', '.join(to_app)}")
    if not to_ext and not to_app:
        print("\n技能目录两侧齐全 ✓")
    return 0


def same_tree(a: Path, b: Path) -> bool:
    cmp = shutil
    for root, dirs, files in os.walk(a):
        rel = Path(root).relative_to(a)
        for f in files:
            p1, p2 = Path(root) / f, b / rel / f
            if not p2.is_file() or p1.stat().st_size != p2.stat().st_size:
                return False
            if p1.read_bytes() != p2.read_bytes():
                return False
        for d in dirs:
            if not (b / rel / d).is_dir():
                return False
    return True


def rm_tree(p: Path) -> None:
    """递归删除，自己处理符号链接（外部挂载上 shutil.rmtree 会因链接报错）。"""
    if p.is_symlink() or p.is_file():
        try:
            p.unlink()
        except FileNotFoundError:
            pass
        return
    if not p.is_dir():
        return
    for child in p.iterdir():
        if child.is_dir() and not child.is_symlink():
            rm_tree(child)
        else:
            try:
                child.unlink()
            except (FileNotFoundError, IsADirectoryError):
                rm_tree(child)
    try:
        p.rmdir()
    except FileNotFoundError:
        pass


def copy_skill(src: Path, dst: Path, dry: bool) -> None:
    if dry:
        print(f"  [dry] {src} → {dst}")
        return
    if dst.exists() or dst.is_symlink():
        rm_tree(dst)
    shutil.copytree(src, dst, symlinks=True)
    print(f"  ✓ {src.name}: {src.parent} → {dst.parent}")


def cmd_sync(args: list[str]) -> int:
    mount = find_mount()
    if mount is None:
        print("❌ 没有外部挂载")
        return 3
    ext = mount / "skills"
    if not ensure_dir(ext) or not ensure_dir(APP_SKILLS):
        print(ERR_MSG, file=sys.stderr)
        return 1

    dry = "--dry" in args
    mode = "push" if "--push" in args else "pull" if "--pull" in args else "union"
    names = [a for a in args if not a.startswith("--")]
    only = names[0] if names else None

    targets = [only] if only else sorted(set(dirs_in(APP_SKILLS)) | set(dirs_in(ext)))
    conflicts = []
    for s in targets:
        ai, ex = APP_SKILLS / s, ext / s
        if mode == "push":
            if ai.is_dir() and not (ex.is_dir() and same_tree(ai, ex)):
                copy_skill(ai, ex, dry)
        elif mode == "pull":
            if ex.is_dir() and not (ai.is_dir() and same_tree(ex, ai)):
                copy_skill(ex, ai, dry)
        else:
            if ex.is_dir() and not ai.is_dir():
                copy_skill(ex, ai, dry)
            elif ai.is_dir() and not ex.is_dir():
                copy_skill(ai, ex, dry)
            elif ai.is_dir() and ex.is_dir() and not same_tree(ai, ex):
                conflicts.append(s)

    for s in conflicts:
        print(f"  ⚠️ 两边不一致（保留 app 版）：{s}（需要时用 --push / --pull）")
    rc = sync_memory(mount, dry, mode)

    print()
    print("外部:", " ".join(dirs_in(ext)) or "（空）")
    print("app :", " ".join(dirs_in(APP_SKILLS)) or "（空）")
    return rc


def sync_memory(mount: Path, dry: bool, mode: str) -> int:
    """记忆文件（GLOBAL.md + 每日日志）双向同步，按修改时间取新。"""
    ext = mount / "memory"
    if not ensure_dir(ext) or not ensure_dir(APP_MEMORY):
        print(ERR_MSG, file=sys.stderr)
        return 1
    names = sorted({p.name for p in APP_MEMORY.glob("*.md")} | {p.name for p in ext.glob("*.md")})
    if not names:
        return 0
    print()
    print("[memory]")
    for n in names:
        a, e = APP_MEMORY / n, ext / n
        if a.is_file() and not e.is_file():
            _copy_file(a, e, dry)
        elif e.is_file() and not a.is_file():
            _copy_file(e, a, dry)
        elif a.is_file() and e.is_file():
            ta, te = a.stat().st_mtime, e.stat().st_mtime
            if a.read_bytes() == e.read_bytes():
                continue
            if mode == "push" or (mode == "union" and ta >= te):
                _copy_file(a, e, dry, "较新→外部")
            elif mode == "pull" or mode == "union":
                _copy_file(e, a, dry, "较新→app")
    return 0


def _copy_file(src: Path, dst: Path, dry: bool, note: str = "") -> None:
    tag = f" ({note})" if note else ""
    if dry:
        print(f"  [dry] {src} → {dst}{tag}")
        return
    shutil.copy2(src, dst)
    print(f"  ✓ {src.name}: {src.parent} → {dst.parent}{tag}")


def project_dirs() -> tuple[Path, Path] | tuple[None, None]:
    mount = find_mount()
    if mount is None:
        return None, None
    proj = mount / "projects"
    if not ensure_dir(proj):
        return None, None
    return proj, mount


def cmd_list(_: list[str]) -> int:
    proj, mount = project_dirs()
    if proj is None:
        print(ERR_MSG or "❌ 没有外部挂载")
        return 3 if not ERR_MSG else 1
    items = dirs_in(proj)
    print(f"挂载: {mount}")
    print("工程:" + ("" if items else " （还没有工程）"))
    for p in items:
        linked = "  ← 当前 chat 已关联" if LINK_FILE.is_file() and LINK_FILE.read_text().strip() == p else ""
        print(f"  - {p}{linked}")
    return 0


def cmd_new(args: list[str]) -> int:
    if not args:
        print("用法: ws.py new <名字>")
        return 2
    name = args[0].strip()
    if not valid_name(name):
        print(f"❌ 非法工程名: {name!r}（不能含 / \\ .. ，也不以 . 或 - 开头）")
        return 2
    proj, mount = project_dirs()
    if proj is None:
        print(ERR_MSG or "❌ 没有外部挂载")
        return 3 if not ERR_MSG else 1
    target = proj / name
    if target.exists():
        print(f"❌ 工程已存在: {name}")
        return 1
    create_project(target, name)
    link_project(name)
    print(f"✅ 已创建并关联: {target}")
    return 0


def create_project(target: Path, name: str) -> None:
    """工程就是一个目录，不生成任何模板文件。"""
    target.mkdir(parents=True, exist_ok=True)


def _hsize(n: int) -> str:
    """人类可读大小：1.2 KB / 18.5 MB。"""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.0f} B"


def tree(target: Path, depth: int = 2, limit: int = 60) -> str:
    """列出工程内容。每行给完整相对路径，不依赖缩进——缩进在任何 UI 里都会被吃掉。"""
    out: list[str] = []
    base_depth = len(target.parts)
    truncated = False

    def walk(d: Path) -> None:
        nonlocal truncated
        for c in sorted(d.iterdir(), key=lambda x: (x.is_file(), x.name)):
            if len(out) >= limit:
                truncated = True
                return
            rel = c.relative_to(target).as_posix()
            lvl = len(c.parts) - base_depth
            if c.is_dir():
                try:
                    n = sum(1 for _ in c.iterdir())
                except OSError:
                    n = 0
                out.append(f"{rel}/  ·  " + ("空" if n == 0 else f"{n} 项"))
                if lvl < depth:
                    walk(c)
            else:
                try:
                    size = _hsize(c.stat().st_size)
                except OSError:
                    size = "?"
                out.append(f"{rel}  ·  {size}")

    if target.is_dir() and any(target.iterdir()):
        walk(target)
    if truncated:
        out.append(f"…（仅显示前 {limit} 项）")
    return "\n".join(out)


def _find_group(obj):
    """CLI 的 JSON 可能层层嵌套，递归找第一个 group 字段。"""
    if isinstance(obj, dict):
        if isinstance(obj.get("group"), str):
            return obj["group"]
        for v in obj.values():
            r = _find_group(v)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_group(v)
            if r is not None:
                return r
    return None


def current_group() -> tuple[str, bool]:
    """取当前会话的分组名。WS_SESSION_GROUP 可覆盖（测试用）。"""
    if "WS_SESSION_GROUP" in os.environ:
        return os.environ["WS_SESSION_GROUP"].strip(), True
    cli = os.environ.get("WS_CLI", "minis-sessions-cli")
    try:
        out = subprocess.run([cli, "status"], capture_output=True,
                             text=True, timeout=25).stdout
        return (_find_group(json.loads(out)) or "").strip(), True
    except Exception:
        return "", False


def prev_files_are_subset_of_target(prev_dir: Path, target: Path) -> bool:
    """旧工程的文件是否都已在目标工程里（同相对路径且字节相同）。判断"别的会话已经迁移过"。"""
    try:
        for f in prev_dir.rglob("*"):
            if not f.is_file():
                continue
            rel = f.relative_to(prev_dir)
            t = target / rel
            if not t.is_file() or t.stat().st_size != f.stat().st_size:
                return False
            if f.stat().st_size < 4 * 1024 * 1024:
                try:
                    if f.read_bytes() != t.read_bytes():
                        return False
                except OSError:
                    return False
        return True
    except OSError:
        return False


def cmd_auto(args: list[str]) -> int:
    """会话开场：分组名 ↔ 工程目录。有分组就确保目录存在、关联本 chat，并列出目录内容。"""
    as_json = "--json" in args
    mount = find_mount()
    if mount is None:
        msg = "❌ 没有找到外部挂载：请在 设置 → 挂载外部文件夹 里选一个「文件」App 文件夹（建议命名 Minis）"
        print(json.dumps({"ok": False, "reason": "no-mount", "message": msg}, ensure_ascii=False) if as_json else msg)
        return 3

    group, ok = current_group()
    if not ok:
        msg = "❌ 无法读取当前会话分组（minis-sessions-cli 不可用）"
        print(json.dumps({"ok": False, "reason": "no-group-api", "message": msg}, ensure_ascii=False) if as_json else msg)
        return 1

    if not group:
        # 未分组 = 没有工程：不碰文件系统，直接走默认逻辑
        msg = "（本会话未分组 → 没有工程，按默认逻辑：草稿放 /var/minis/workspace/，跨 chat 复用放 /var/minis/shared/）"
        print(json.dumps({"ok": True, "group": "", "project": None}, ensure_ascii=False) if as_json else msg)
        return 0

    proj = mount / "projects"
    if not ensure_dir(proj):
        print(json.dumps({"ok": False, "reason": "dir-error", "message": ERR_MSG}, ensure_ascii=False) if as_json else ERR_MSG)
        return 1

    if not valid_name(group):
        msg = f"❌ 分组名不能直接当工程名: {group!r}（不能含斜杠或以点开头），请改分组名"
        print(json.dumps({"ok": False, "reason": "bad-name", "group": group, "message": msg}, ensure_ascii=False) if as_json else msg)
        return 2

    target = proj / group
    created = False
    if not target.is_dir():
        if not ensure_dir(target):
            print(json.dumps({"ok": False, "reason": "dir-error", "message": ERR_MSG}, ensure_ascii=False) if as_json else ERR_MSG)
            return 1
        create_project(target, group)
        created = True

    prev = LINK_FILE.read_text().strip() if LINK_FILE.is_file() else ""
    link_project(group)
    hint = ""
    prev_dir = proj / prev if prev else None
    if prev and prev != group and prev_dir and prev_dir.is_dir():
        old_files = sum(1 for x in prev_dir.rglob("*") if x.is_file())
        new_files = sum(1 for x in target.rglob("*") if x.is_file())
        if old_files == 0:
            # 旧工程是空的：只是切换工程，不是改名，不提醒、不留线索
            hint = ""
        else:
            try:
                PREV_FILE.parent.mkdir(parents=True, exist_ok=True)
                PREV_FILE.write_text(prev + "\n", encoding="utf-8")
            except OSError:
                pass
            if new_files == 0:
                hint = (f"ℹ️ 当前关联的是 {prev}（{old_files} 个文件），但分组名是 {group}；"
                        f"如确认是改名，跑：ws.py migrate（无需参数）")
            elif prev_files_are_subset_of_target(prev_dir, target):
                hint = (f"ℹ️ 已切到同名工程 {group}；旧工程 {prev} 里的文件这里都有，"
                        f"应是其他会话迁移过。旧工程未删除，确认无用后手动清理")
            else:
                hint = (f"ℹ️ 当前关联的是 {prev}（{old_files} 个文件），新工程 {group} 已有 {new_files} 个文件；"
                        f"确认要合并再跑 ws.py migrate（同名路径会中止）")
    elif PREV_FILE.is_file() and prev == group:
        PREV_FILE.unlink(missing_ok=True)
    listing = tree(target)

    if as_json:
        print(json.dumps({"ok": True, "group": group, "project": str(target),
                          "created": created, "contents": listing,
                          "hint": hint}, ensure_ascii=False))
        return 0

    print(("＋ 已创建工程并关联" if created else "✅ 已关联工程") + f": {target}")
    if hint:
        print(hint)
    if listing:
        print("--- 工程内容 ---")
        print(listing)
    else:
        print("（工程是空的，本次产物直接写进这个目录）")
    return 0


def link_project(name: str) -> None:
    LINK_FILE.parent.mkdir(parents=True, exist_ok=True)
    LINK_FILE.write_text(name + "\n", encoding="utf-8")


def cmd_link(args: list[str]) -> int:
    if not args:
        print("用法: ws.py link <名字>")
        return 2
    name = args[0].strip()
    if not valid_name(name):
        print(f"❌ 非法工程名: {name!r}")
        return 2
    proj, _ = project_dirs()
    if proj is None:
        print(ERR_MSG or "❌ 没有外部挂载")
        return 3 if not ERR_MSG else 1
    target = proj / name
    if not target.is_dir():
        # 新分组的工程还没建过：关联时直接建出来
        if not ensure_dir(target):
            print(ERR_MSG)
            return 1
        link_project(name)
        print(f"＋ 已创建并关联: {target}")
        print("   （该工程原本不存在，已建为空目录；本次产物直接写进这里）")
        return 0
    link_project(name)
    print(f"✅ 已关联: {proj / name}")
    return 0


def _blocked(rel: Path, new: Path) -> bool:
    """目标路径的某一级父目录在对方那里是个文件 → 无法落位。"""
    cur = new
    for part in rel.parts[:-1]:
        cur = cur / part
        if cur.exists() and not cur.is_dir():
            return True
    return False


def _plan_merge(old: Path, new: Path):
    """预演合并：返回 (可搬, 冲突)。任何同名文件/目录都算冲突，整体中止。"""
    to_move: list[Path] = []
    conflicts: list[Path] = []
    for src in sorted(old.rglob("*")):
        if not src.is_file():
            continue
        rel = src.relative_to(old)
        dst = new / rel
        if dst.exists() or dst.is_symlink() or _blocked(rel, new):
            conflicts.append(rel)
        else:
            to_move.append(rel)
    return to_move, conflicts


def cmd_migrate(args: list[str]) -> int:
    """migrate <新名> | migrate <旧名> <新名> [--dry] —— 把旧工程复制到新名，旧目录保留。"""
    dry = "--dry" in args
    rest = [a for a in args if a != "--dry"]
    proj, _ = project_dirs()
    if proj is None:
        print(ERR_MSG or "❌ 没有外部挂载")
        return 3
    if len(rest) > 2:
        print("用法: ws.py migrate [旧名 新名] | migrate [新名] [--dry]")
        return 2

    if len(rest) == 2:
        old_name, new_name = rest[0].strip(), rest[1].strip()
    elif len(rest) == 1:
        new_name = rest[0].strip()
        old_name = LINK_FILE.read_text().strip() if LINK_FILE.is_file() else ""
        if not old_name:
            print("❌ 只有一个名字时需要旧工程：ws.py migrate <旧名> <新名>")
            return 2
    else:
        # 零参数：用户只改了 App 侧分组名，旧名从 .project-prev / .project 推
        new_name, ok = current_group()
        if not ok:
            print("❌ 无法读取当前会话分组（minis-sessions-cli 不可用）；请显式给名字：ws.py migrate <旧> <新>")
            return 1
        if not new_name:
            print("❌ 当前会话没有分组名，无法推断新工程名；请显式给名字：ws.py migrate <旧> <新>")
            return 2
        old_name = ""
        if PREV_FILE.is_file():
            cand = PREV_FILE.read_text().strip()
            if cand and valid_name(cand) and (proj / cand).is_dir():
                old_name = cand
        if not old_name and LINK_FILE.is_file():
            old_name = LINK_FILE.read_text().strip()
        # 线索全无也照常走下去：按"旧无"处理（复用或创建新工程）

    for n in ([old_name] if old_name else []) + [new_name]:
        if not valid_name(n):
            print(f"❌ 非法工程名: {n!r}（不能含 / \\ .. ，也不以 . 或 - 开头）")
            return 2
    if old_name and old_name == new_name:
        if PREV_FILE.is_file():
            PREV_FILE.unlink(missing_ok=True)
        print(f"✅ 已是同名（{new_name}），无需迁移")
        return 0 if not rest else 2

    old = (proj / old_name) if old_name else None
    new = proj / new_name
    if new.exists() and not new.is_dir():
        print(f"❌ 目标位置被文件占用: {new}")
        return 1

    # 旧不存在（或无旧名线索）：只处理新工程，绝不凭空复制
    if old is None or not old.is_dir():
        if old_name:
            print(f"ℹ️ 原工程 \"{old_name}\" 不存在，没有可复制的内容")
        else:
            print("ℹ️ 没有旧工程线索（.project-prev / .project 为空），没有可复制的内容")
        if new.is_dir():
            n = sum(1 for x in new.rglob("*") if x.is_file())
            if dry:
                print(f"🔍 预演：将复用已有工程 {new_name}（{n} 个文件），不做复制")
                return 0
            if PREV_FILE.is_file():
                PREV_FILE.unlink(missing_ok=True)
            link_project(new_name)
            print(f"✅ 已复用已有工程 {new_name}（{n} 个文件）")
            print(f"   工程目录: {new}")
            print(f"   ✅ 当前 chat 已改关联到 {new_name}")
            return 0
        if dry:
            print(f"🔍 预演：将创建空工程 {new_name}，不做复制")
            return 0
        if not ensure_dir(new):
            print(ERR_MSG)
            return 1
        if PREV_FILE.is_file():
            PREV_FILE.unlink(missing_ok=True)
        link_project(new_name)
        print(f"✅ 已创建空工程 {new_name}（原工程不存在，没有内容可复制）")
        print(f"   工程目录: {new}")
        print(f"   ✅ 当前 chat 已改关联到 {new_name}")
        return 0

    to_move, conflicts = _plan_merge(old, new)

    if conflicts:
        print(f"❌ 合并中止：目标工程里已有 {len(conflicts)} 个同名文件/目录，未做任何改动")
        for rel in conflicts:
            print(f"  ⚠ {rel.as_posix()}")
        print(f"   旧工程保持原样：{old}")
        print(f"   目标工程保持原样：{new}")
        print("   同名不代表内容相同，这里不替你判断谁该留下。请手动处理后重跑，或换一个不冲突的新名。")
        return 1

    if dry:
        print(f"🔍 预演 {old_name} → {new_name}："
              + ("新建目标目录，" if not new.is_dir() else "合并进已有目录，")
              + f"复制 {len(to_move)} 个文件（旧工程保留）")
        for rel in to_move[:20]:
            print(f"  → {rel.as_posix()}")
        if len(to_move) > 20:
            print(f"  …（共 {len(to_move)} 个）")
        return 0

    created = not new.is_dir()
    if not ensure_dir(new):
        print(ERR_MSG)
        return 1
    copied = 0
    try:
        for rel in to_move:
            src, dst = old / rel, new / rel
            ensure_dir(dst.parent)
            if src.is_symlink():
                if not dst.exists() and not dst.is_symlink():
                    os.symlink(os.readlink(src), dst)
            else:
                shutil.copy2(str(src), str(dst))
            copied += 1
    except OSError as e:
        print(f"❌ 复制中断（已复制 {copied} 个）：{e}")
        print(f"   旧工程完好: {old}")
        print(f"   目标目录可能不完整: {new}（请检查后删除或重跑）")
        return 1
    if PREV_FILE.is_file():
        PREV_FILE.unlink(missing_ok=True)
    linked = LINK_FILE.read_text().strip() if LINK_FILE.is_file() else ""
    relinked = linked == old_name
    if relinked:
        link_project(new_name)

    print(f"✅ 已复制 {old_name} → {new_name}"
          f"（{'新建目录' if created else '合并'}，复制 {copied} 个文件）")
    print(f"   工程目录: {new}")
    print(f"   旧工程保留: {old}（同一分组的其他会话可能仍在用它，如需清理请确认后手动删除）")
    if relinked:
        print(f"   ✅ 当前 chat 已改关联到 {new_name}")
    elif linked:
        print(f"   （当前 chat 关联的是 {linked}，未改动）")
    return 0


def cmd_which(_: list[str]) -> int:
    proj, _ = project_dirs()
    if proj is None:
        print(ERR_MSG or "❌ 没有外部挂载")
        return 3 if not ERR_MSG else 1
    if not LINK_FILE.is_file():
        print("（当前 chat 未关联工程）")
        return 4
    name = LINK_FILE.read_text().strip()
    print(proj / name)
    if not (proj / name).is_dir():
        print(f"⚠️ 工程目录已不存在: {proj / name}", file=sys.stderr)
    return 0


COMMANDS = {
    "auto": cmd_auto,
    "bootstrap": cmd_bootstrap,
    "sync": cmd_sync,
    "list": cmd_list,
    "new": cmd_new,
    "link": cmd_link,
    "which": cmd_which,
    "migrate": cmd_migrate,
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0 if len(sys.argv) > 1 else 2
    cmd = sys.argv[1]
    if cmd not in COMMANDS:
        print(f"未知子命令: {cmd}")
        return 2
    return COMMANDS[cmd](sys.argv[2:])


if __name__ == "__main__":
    sys.exit(main())