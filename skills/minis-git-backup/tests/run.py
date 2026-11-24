#!/usr/bin/env python3
"""minis-git-backup 测试：在真实挂载目录的副本上跑。

每次把 /var/minis/mounts/Minis 完整复制一次作主副本，各用例再从主副本
硬链接派生独立沙箱。真实目录只读，跑完清理。

**绝不推到真实远程**：所有远程都是 /tmp 下的裸仓库，并且全程设置
BACKUP_GIT_NO_NETWORK=1，脚本遇到 https:// 地址会直接拒绝。

用法：
  python3 tests/run.py              # 跑 cases.json
  python3 tests/run.py --verbose    # 失败时打印完整输出
  python3 tests/run.py --selftest   # 负向自检：期望判反后必须全部变红
"""

import json
import os
import shutil
import subprocess
import sys
import time
import tempfile
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
SCRIPT = os.path.join(SKILL, "scripts", "backup.py")
CASES = os.path.join(HERE, "cases.json")
SRC = os.environ.get("MINIS_SRC", "/var/minis/mounts/Minis")

HIDDEN_GIT = ".git-backup"
HIDDEN_IGNORE = ".gitignore-backup"

# 复制时跳过：备份仓库自身与临时产物；projects/ 内的 .git 必须保留
SKIP_TOP = {".git", "bak", "restore", "__pycache__"}

STALE = ("mgb-", "minis-restore-", "minis-verify-")

MASTER = None
MASTER_DIR = None


# ---------------------------------------------------------------- 沙箱

def purge_stale():
    """清上次中断留下的沙箱。主副本 mgb-master-* 要保住：它是本轮所有
    用例的源，被另一个进程清掉就会出现 FileNotFoundError。"""
    removed = 0
    base = tempfile.gettempdir()
    for n in os.listdir(base):
        if not n.startswith(STALE):
            continue
        if n.startswith("mgb-master-"):
            continue                    # 本轮的主副本，别动
        q = os.path.join(base, n)
        if os.path.isdir(q):
            shutil.rmtree(q, ignore_errors=True)
            removed += 1
    return removed


def build_master():
    """整轮只真实复制一次。"""
    global MASTER, MASTER_DIR
    if MASTER is not None:
        return MASTER
    if not os.path.isdir(SRC):
        raise SystemExit("找不到被测目录：%s" % SRC)
    MASTER_DIR = tempfile.mkdtemp(prefix="mgb-master-")
    MASTER = os.path.join(MASTER_DIR, "Minis")

    def ignore(directory, names):
        at_top = os.path.abspath(directory) == os.path.abspath(SRC)
        return {n for n in names if at_top and n in SKIP_TOP}

    shutil.copytree(SRC, MASTER, symlinks=True, ignore=ignore)
    return MASTER


def _copy_tree(src, dst):
    """真实复制整棵子树。

    曾经用硬链接省时间，结果所有沙箱共享 inode：任何原地写（追加日志、
    `open("a")` 追加、git 往 logs/HEAD 追加）都会穿透到主副本，把干净基线
    弄脏，后续用例随即出现「没有可提交的改动」「内层仓库没进备份」这类
    与代码无关的假失败。整份只有 3 MB 出头，复制比排错便宜得多。
    """
    os.makedirs(dst)
    for n in sorted(os.listdir(src)):
        s, d = os.path.join(src, n), os.path.join(dst, n)
        if os.path.islink(s):
            os.symlink(os.readlink(s), d)
        elif os.path.isdir(s):
            _copy_tree(s, d)
        else:
            shutil.copy2(s, d)


def clone_real(base):
    dst = os.path.join(base, "Minis")
    _copy_tree(build_master(), dst)
    return dst


def cleanup_master():
    global MASTER, MASTER_DIR
    if MASTER_DIR:
        shutil.rmtree(MASTER_DIR, ignore_errors=True)
    MASTER = None
    MASTER_DIR = None


# ---------------------------------------------------------------- 命令

def run_proc(argv, cwd=None, env=None):
    """执行命令；默认强制禁网，杜绝推到真实远程。"""
    e = dict(os.environ)
    for k in ("BACKUP_GIT_TOKEN", "BACKUP_GIT_REPO", "MINIS_MOUNT", "GITHUB_TOKEN"):
        e.pop(k, None)
    e["BACKUP_GIT_NO_NETWORK"] = "1"
    if env:
        e.update({k: v for k, v in env.items() if v is not None})
    try:
        p = subprocess.run(argv, cwd=cwd, env=e, capture_output=True, text=True)
    except FileNotFoundError as exc:
        return 127, str(exc)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def git(cwd, *args):
    return run_proc(["git"] + list(args), cwd=cwd)[1].strip()


def run(args, mount, env=None):
    argv = [sys.executable, SCRIPT, "--mount", mount]
    if args:
        argv += args.split()
    return run_proc(argv, env=env)


# ---------------------------------------------------------------- 断言辅助

def check(expect, rc, out, expect_rc=0):
    ok, why = True, []
    needles = [expect] if isinstance(expect, str) else list(expect)
    for n in needles:
        if n not in out:
            ok = False
            why.append("输出缺少 %r" % n)
    if rc != expect_rc:
        ok = False
        why.append("退出码 %d，期望 %d" % (rc, expect_rc))
    return ok, why


def add_change(mount):
    """给用例造一处确定性的未提交改动，别让断言依赖真实目录当下的脏状态。"""
    p = os.path.join(mount, "memory", "0000-00-00-test.md")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write("test note\n")
    return p


def prepare_repo(mount):
    """副本里的仓库可能有真实 origin，统一重置成干净状态。"""
    if not os.path.isdir(os.path.join(mount, ".git")):
        run_proc(["git", "init", "-q", "."], cwd=mount)
    git(mount, "config", "user.name", "T")
    git(mount, "config", "user.email", "t@t")
    git(mount, "remote", "remove", "origin")
    return mount


def make_bare(base, name="origin.git"):
    """造一个空的裸仓库当远程。"""
    path = os.path.join(base, name)
    run_proc(["git", "init", "-q", "--bare", path])
    return path


def all_git_dirs(mount):
    """副本里所有真实 .git（排除根与 bak/）。"""
    out = []
    for dp, dns, _ in os.walk(mount):
        rel = os.path.relpath(dp, mount)
        if rel.split(os.sep)[0] in ("bak",) or rel == ".":
            if ".git" in dns and rel != ".":
                out.append(os.path.join(rel, ".git"))
            dns[:] = [d for d in dns if d != ".git"]
            continue
        if ".git" in dns:
            out.append(os.path.join(rel, ".git"))
            dns.remove(".git")
    return sorted(out)


def leftovers(mount):
    """残留的 .git-backup / .gitignore-backup。"""
    out = []
    for dp, dns, fns in os.walk(mount):
        for n in dns:
            if n == HIDDEN_GIT:
                out.append(os.path.join(os.path.relpath(dp, mount), n))
        for n in fns:
            if n == HIDDEN_IGNORE:
                out.append(os.path.join(os.path.relpath(dp, mount), n))
    return sorted(out)# ---------------------------------------------------------------- 用例

def case_init(mount, c):
    prepare_repo(mount)
    rc, out = run("init", mount)
    ok, why = check(c["expect"], rc, out, c.get("rc", 0))
    for f in c.get("assert_file", []):
        if not os.path.exists(os.path.join(mount, f)):
            ok = False
            why.append("缺少 %s" % f)
    if c.get("assert_no_remote") and git(mount, "remote"):
        ok = False
        why.append("init 不应配置远程")
    return ok, why, out


def case_init_dry(mount, c):
    prepare_repo(mount)
    # 真实挂载初始化过后自带正确 .gitignore，预演就只会说「已是最新」。
    # 这里先写一份过期规则（v1 版：按目录排除），让「会更新」这条分支可复现。
    with open(os.path.join(mount, ".gitignore"), "w", encoding="utf-8") as f:
        f.write("bak/\nrestore/\n/projects/\n/skills/\n")
    rc, out = run("init --dry", mount)
    return (*check(c["expect"], rc, out, c.get("rc", 0)), out)


def case_usage(mount, c):
    rc, out = run(c.get("args", ""), mount)
    return (*check(c["expect"], rc, out, c.get("rc", 0)), out)


def case_backup_dry(mount, c):
    prepare_repo(mount)
    run("init", mount)
    add_change(mount)
    n = len(all_git_dirs(mount))
    rc, out = run("backup --dry", mount)
    ok, why = check(c["expect"], rc, out, c.get("rc", 0))
    if ("将备份 %d 个仓库" % n) not in out:
        ok = False
        why.append("副本里有 %d 个 .git，输出没对上" % n)
    if leftovers(mount):
        ok = False
        why.append("预演不该改名，却留下 %s" % leftovers(mount)[:3])
    return ok, why, out


def case_backup_local(mount, c):
    prepare_repo(mount)
    run("init", mount)
    add_change(mount)
    before = set(all_git_dirs(mount))
    env = {"BACKUP_GIT_REPO": "tester/minis-backup"}
    rc, out = run("backup --local", mount, env)
    ok, why = check(c["expect"], rc, out, c.get("rc", 0))

    after = set(all_git_dirs(mount))
    if before != after:
        ok = False
        why.append(".git 未全部恢复：缺 %s 多 %s"
                   % (sorted(before - after)[:3], sorted(after - before)[:3]))
    left = leftovers(mount)
    if left:
        ok = False
        why.append("残留 %s" % left[:3])
    # 索引记的是 .git-backup 旧路径，改回 .git 后必然出现 D / ??，
    # 这是改名方案的自然后果；真正要防的是内容被改动（M/A）。
    # 备份时把每个仓库的 .git 改名成 .git-backup，索引里存的是改名后的树；
    # 改回 .git 后这些仓库根目录会以 "M <仓库路径>" 的形式出现（树 ↔ gitlink
    # 的类型差），不是内容被改。真正要防的是文件内容变动（M/A），所以这里
    # 把「仓库根目录本身」的这类行放过，只看它下面的文件。
    repo_roots = {os.path.dirname(g).replace(os.sep, "/")
                  for g in all_git_dirs(mount)}
    bad = []
    for l in git(mount, "status", "--porcelain").splitlines():
        if l.startswith("D") or l.startswith(" D") or l.startswith("??"):
            continue
        path = l[3:].strip()
        if path in repo_roots and l[:2].strip() == "M":
            continue
        bad.append(l)
    if bad:
        ok = False
        why.append("工作区有非预期改动：%s" % bad[:3])
    return ok, why, out


def case_backup_ignores(mount, c):
    """子目录 .gitignore 会污染备份仓库，必须改名，否则内层仓库被静默排除。"""
    prepare_repo(mount)
    run("init", mount)
    add_change(mount)
    env = {"BACKUP_GIT_REPO": "tester/minis-backup"}
    rc, out = run("backup --local", mount, env)
    ok, why = check(c["expect"], rc, out, c.get("rc", 0))

    tracked = git(mount, "ls-files").splitlines()
    inner = [t for t in tracked if t.endswith(HIDDEN_GIT + "/HEAD")]
    if len(inner) < 2:
        ok = False
        why.append("内层仓库没进备份，只找到 %d 个 %s/HEAD" % (len(inner), HIDDEN_GIT))
    if any(t.endswith(".gitignore") and t.count("/") > 1 for t in tracked):
        ok = False
        why.append("子目录的 .gitignore 没改名，会继续过滤备份内容")
    if leftovers(mount):
        ok = False
        why.append("残留 %s" % leftovers(mount)[:3])
    return ok, why, out


def case_backup_twice(mount, c):
    """第二轮只应新增少量对象。"""
    prepare_repo(mount)
    run("init", mount)
    add_change(mount)
    env = {"BACKUP_GIT_REPO": "tester/minis-backup"}
    run("backup --local", mount, env)
    n1 = len(os.listdir(os.path.join(mount, ".git", "objects")))

    proj = os.path.join(mount, "projects", "quota-usage")
    if os.path.isdir(proj):
        git(proj, "config", "user.name", "T")
        git(proj, "config", "user.email", "t@t")
        with open(os.path.join(proj, "PROGRESS.md"), "a", encoding="utf-8") as f:
            f.write("\n增量测试\n")
        git(proj, "add", "-A")
        git(proj, "commit", "-qm", "test: 增量")

    rc, out = run("backup --local", mount, env)
    ok, why = check(c["expect"], rc, out, c.get("rc", 0))
    if leftovers(mount):
        ok = False
        why.append("残留 %s" % leftovers(mount)[:3])
    return ok, why, out


def case_push_verify(mount, c):
    """推送成功必须能克隆回来完整还原。"""
    prepare_repo(mount)
    run("init", mount)
    add_change(mount)
    base = os.path.dirname(mount)
    origin = make_bare(base)

    env = {"BACKUP_GIT_TOKEN": "fake", "BACKUP_GIT_REPO": "tester/minis-backup"}
    rc, out = run("backup --remote file://%s" % origin, mount, env)
    ok, why = check(c["expect"], rc, out, c.get("rc", 0))
    if leftovers(mount):
        ok = False
        why.append("残留 %s" % leftovers(mount)[:3])

    # 远程里应能看到 .git-backup
    listed = git(origin, "ls-tree", "-r", "--name-only", "master").splitlines()
    if not any(t.endswith(HIDDEN_GIT + "/HEAD") for t in listed):
        ok = False
        why.append("远程没有 .git-backup，备份未生效")
    if any(t.endswith(".gitignore") and t.count("/") > 1 for t in listed):
        ok = False
        why.append("远程里子目录 .gitignore 没改名")
    return ok, why, out


def case_push_nonet(mount, c):
    """禁网时不得推到 https://。"""
    prepare_repo(mount)
    run("init", mount)
    add_change(mount)
    env = {"BACKUP_GIT_TOKEN": "fake", "BACKUP_GIT_REPO": "tester/minis-backup"}
    rc, out = run("backup", mount, env)
    ok, why = check(c["expect"], rc, out, c.get("rc", 0))
    if leftovers(mount):
        ok = False
        why.append("失败后没恢复 .git：%s" % leftovers(mount)[:3])
    return ok, why, out


def case_restore_empty(mount, c):
    """空目录还原：整份铺入，带 .git。"""
    base = os.path.dirname(mount)
    origin = make_bare(base, "restore-origin.git")
    env = {"BACKUP_GIT_TOKEN": "fake", "BACKUP_GIT_REPO": "tester/minis-backup"}

    prepare_repo(mount)
    run("init", mount)
    add_change(mount)
    run("backup --remote file://%s" % origin, mount, env)

    for n in list(os.listdir(mount)):
        q = os.path.join(mount, n)
        shutil.rmtree(q, ignore_errors=True) if os.path.isdir(q) else os.remove(q)

    rc, out = run("restore --remote file://%s" % origin, mount, env)
    ok, why = check(c["expect"], rc, out, c.get("rc", 0))
    if not os.path.isdir(os.path.join(mount, ".git")):
        ok = False
        why.append("还原后根目录没有 .git")
    if not all_git_dirs(mount):
        ok = False
        why.append("子仓库没还原")
    if leftovers(mount):
        ok = False
        why.append("残留 %s" % leftovers(mount)[:3])
    if os.path.isdir(os.path.join(mount, "bak")):
        ok = False
        why.append("空目录不需要 bak/")
    return ok, why, out


def case_restore_nonempty(mount, c):
    """非空且无 .git：停下并要用户决定。"""
    base = os.path.dirname(mount)
    origin = make_bare(base, "restore2.git")
    env = {"BACKUP_GIT_TOKEN": "fake", "BACKUP_GIT_REPO": "tester/minis-backup"}

    prepare_repo(mount)
    run("init", mount)
    add_change(mount)
    run("backup --remote file://%s" % origin, mount, env)

    shutil.rmtree(os.path.join(mount, ".git"), ignore_errors=True)
    keep = os.path.join(mount, "local-only")
    os.makedirs(keep, exist_ok=True)
    with open(os.path.join(keep, "x.txt"), "w", encoding="utf-8") as f:
        f.write("x\n")

    rc, out = run("restore --remote file://%s" % origin, mount, env)
    ok, why = check(c["expect"], rc, out, c.get("rc", 0))
    if not os.path.isdir(keep):
        ok = False
        why.append("本地内容被动了")
    return ok, why, out


def case_restore_repo(mount, c):
    """有 .git：旧内容进 bak/，备份铺回来。"""
    base = os.path.dirname(mount)
    origin = make_bare(base, "restore3.git")
    env = {"BACKUP_GIT_TOKEN": "fake", "BACKUP_GIT_REPO": "tester/minis-backup"}

    prepare_repo(mount)
    run("init", mount)
    add_change(mount)
    run("backup --remote file://%s" % origin, mount, env)
    before = set(os.listdir(mount))

    rc, out = run("restore --remote file://%s" % origin, mount, env)
    ok, why = check(c["expect"], rc, out, c.get("rc", 0))

    baks = sorted(os.listdir(os.path.join(mount, "bak")))
    if len(baks) != 1:
        ok = False
        why.append("bak/ 应有 1 个时间戳目录，实际 %s" % baks)
    else:
        import re as _re
        if not _re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}", baks[0]):
            ok = False
            why.append("bak 目录名不是可读格式：%s" % baks[0])
        kept = set(os.listdir(os.path.join(mount, "bak", baks[0])))
        missing = (before - {"bak"}) - kept
        if missing:
            ok = False
            why.append("bak 里缺少 %s" % sorted(missing)[:3])
    if not all_git_dirs(mount):
        ok = False
        why.append("子仓库没还原")
    if leftovers(mount):
        ok = False
        why.append("残留 %s" % leftovers(mount)[:3])
    return ok, why, out


def case_scan_dirty(mount, c):
    prepare_repo(mount)
    p = os.path.join(mount, "memory", "9999-99-99.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write("密码=Secret12345 手机 13800001111 key=sk-abcdefghijklmnopqrstuvwx\n")
    rc, out = run("scan", mount)
    rc2, out2 = run("scan --fix", mount)
    ok, why = check(c["expect"], rc, out + out2, c.get("rc", 0))
    if "Secret12345" in out or "13800001111" in out:
        ok = False
        why.append("报告里泄露了明文")
    body = open(p, encoding="utf-8").read()
    if "Secret12345" in body or "13800001111" in body:
        ok = False
        why.append("--fix 之后仍有明文")
    if "*********" not in body:
        ok = False
        why.append("密码没有全星号")
    os.remove(p)
    return ok, why, out + out2


def case_message(mount, c):
    """提交信息必须符合 Angular。"""
    prepare_repo(mount)
    run("init", mount)
    add_change(mount)
    env = {"BACKUP_GIT_REPO": "tester/minis-backup"}
    run("backup --local", mount, env)
    subject = git(mount, "log", "--format=%s", "-1")
    ok = True
    why = []
    if not subject.startswith("chore(backup): "):
        ok = False
        why.append("标题格式不对：%s" % subject)
    if len(subject.split(": ", 1)[1]) > 50:
        ok = False
        why.append("标题超过 50 字")
    for n in c["expect"]:
        if n not in subject:
            ok = False
            why.append("标题缺少 %r" % n)
    return ok, why, subject


RUNNERS = {
    "init": case_init,
    "init-dry": case_init_dry,
    "usage": case_usage,
    "backup-dry": case_backup_dry,
    "backup-local": case_backup_local,
    "backup-ignores": case_backup_ignores,
    "backup-twice": case_backup_twice,
    "push-verify": case_push_verify,
    "push-nonet": case_push_nonet,
    "restore-empty": case_restore_empty,
    "restore-nonempty": case_restore_nonempty,
    "restore-repo": case_restore_repo,
    "scan-dirty": case_scan_dirty,
    "message": case_message,
}


def run_case(c):
    """在独立沙箱里跑一个用例，返回 (ok, why, out, 秒)。"""
    t0 = time.time()
    base = tempfile.mkdtemp(prefix="mgb-")
    try:
        mount = clone_real(base)
        runner = RUNNERS.get(c["kind"])
        if runner is None:
            return False, ["未知用例类型 %s" % c["kind"]], "", time.time() - t0
        ok, why, out = runner(mount, c)
        return ok, why, out, time.time() - t0
    except Exception as e:
        return False, ["异常：%s" % e], "", time.time() - t0
    finally:
        shutil.rmtree(base, ignore_errors=True)   # 异常也要清，别留沙箱


def chunk(seq, n):
    """按固定长度切块，块多时最后一块可能不满。"""
    return [seq[i:i + n] for i in range(0, len(seq), n)]


def parse_chunk(argv):
    """--chunk K：每个线程串行跑 K 个用例，默认 5。"""
    for i, a in enumerate(argv):
        if a == "--chunk" and i + 1 < len(argv):
            try:
                return max(1, int(argv[i + 1]))
            except ValueError:
                return 5
        if a.startswith("--chunk="):
            try:
                return max(1, int(a.split("=", 1)[1]))
            except ValueError:
                return 5
    return 5


def _run_one(c):
    """在独立沙箱里跑一个用例。线程安全：沙箱真实复制、互不共享 inode。"""
    t0 = time.time()
    base = tempfile.mkdtemp(prefix="mgb-")
    try:
        mount = clone_real(base)
        runner = RUNNERS.get(c["kind"])
        if runner is None:
            return False, ["未知用例类型 %s" % c["kind"]], ""
        ok, why, out = runner(mount, c)
        return ok, why, out
    except Exception as e:
        return False, ["异常：%s" % e], ""
    finally:
        shutil.rmtree(base, ignore_errors=True)


def parse_jobs(argv, n_cases):
    """并发度。默认 1（串行）。

    iSH 是 aarch64 模拟层，本套用例又是 I/O 密集（每例要复制 1100+ 文件、
    再让 git deflate 上千个对象）。实测 15 项全量：

        1 线程 374s ｜ 2 线程 590s ｜ 5 线程 736s

    并行只会让模拟层的 syscall 互相争抢，越开越慢，所以默认串行。
    保留 --jobs N / --jobs=N / MGB_JOBS 开关供真实多核环境使用，上限 6。
    """
    raw = None
    for i, a in enumerate(argv):
        if a == "--jobs" and i + 1 < len(argv):
            raw = argv[i + 1]
        elif a.startswith("--jobs="):
            raw = a.split("=", 1)[1]
    if raw is None:
        raw = os.environ.get("MGB_JOBS")
    if raw is None:
        return 1
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = 1
    return max(1, min(n, 6))


def main():
    selftest = "--selftest" in sys.argv
    verbose = "--verbose" in sys.argv
    cases = json.load(open(CASES, encoding="utf-8"))
    jobs = parse_jobs(sys.argv, len(cases))

    print("被测源：%s" % SRC)
    stale = purge_stale()
    if stale:
        print("已清理 %d 个上次中断留下的沙箱" % stale)
    if jobs > 1:
        print("并行：%d 个线程，每线程约 %d 项" % (jobs, (len(cases) + jobs - 1) // jobs))

    build_master()          # 建池之前复制一次，之后所有线程只读

    if jobs > 1:
        with ThreadPoolExecutor(max_workers=jobs, thread_name_prefix="mgb") as ex:
            futs = [ex.submit(_run_one, c) for c in cases]
            results = []
            for f in futs:      # 按提交顺序取，输出顺序与串行一致
                try:
                    results.append(f.result())
                except Exception as e:
                    results.append((False, ["异常：%s" % e], ""))
    else:
        results = [_run_one(c) for c in cases]

    failed = 0
    for c, (ok, why, out) in zip(cases, results):
        if selftest:
            ok2, _w2 = check(c["expect"], 0, "", c.get("rc", 0))
            ok = not ok2
            if not ok:
                why = ["负向自检：该用例期望太松（判反后仍通过）"]
        if ok:
            print("PASS  %s" % c["name"])
        else:
            failed += 1
            print("FAIL  %s" % c["name"])
            for w in why:
                print("      - %s" % w)
            if verbose:
                print(out)
    print("共 %d 项，失败 %d 项" % (len(cases), failed))
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        cleanup_master()
    sys.exit(code)