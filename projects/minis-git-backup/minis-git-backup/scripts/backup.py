#!/usr/bin/env python3
"""minis-git-backup：把 Minis 挂载目录备份到 GitHub，并从远程还原。

核心思路：git 拒绝跟踪任何 `.git` 路径（`git add -f x/.git/y` 会报
"is in submodule"），所以备份时把每个 `.git` 临时改名成 `.git-backup`，
让 git 当普通文件跟踪，提交推送后立刻改回原名。还原时反向改回来。

这样远程能看到全部工作区文件，子仓库的 objects 也按对象去重 —— 改一个
文件只增该文件大小的对象，不会整包重来。

子命令：init / remote / backup / scan / restore。
参数、退出码与已知限制见 ../references/commands.md。
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

VERSION = "2.0.0"

# 退出码
RC_OK = 0
RC_FAIL = 1
RC_USAGE = 2
RC_NO_MOUNT = 3
RC_NOT_INIT = 4
RC_NO_TOKEN = 5
RC_NEED_CONFIRM = 6

MOUNT_ENV = "MINIS_MOUNT"
HIDDEN_GIT = ".git-backup"      # 备份期间的 .git 临时名
IGNORE_NAME = ".gitignore"
HIDDEN_IGNORE = ".gitignore-backup"   # 备份期间的 .gitignore 临时名
STAGE_DIR = "bak"               # 还原时旧内容的暂存目录

IGNORE_LINES = [
    "# minis-git-backup 自动生成：除暂存与可重建缓存，其余全部入库",
    "",
    "# 还原时旧内容的暂存区，与备份重复",
    "bak/",
    "",
    "# 可重建的缓存，入库只会产生噪音",
    "__pycache__/",
    "*.pyc",
    ".DS_Store",
]


class Fail(Exception):
    def __init__(self, msg, rc=RC_FAIL):
        super().__init__(msg)
        self.rc = rc


def mount_root():
    root = os.environ.get(MOUNT_ENV) or "/var/minis/mounts/Minis"
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise Fail("找不到挂载目录：%s" % root, RC_NO_MOUNT)
    return root


def git(root, *args, check=True):
    """在 root 里跑 git，返回 (rc, stdout, stderr)。"""
    p = subprocess.run(["git", "-C", root] + list(args),
                       capture_output=True, text=True)
    if check and p.returncode != 0:
        raise Fail("git %s 失败：%s" % (" ".join(args), (p.stderr or p.stdout).strip()))
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def run_proc(argv):
    """执行任意命令，返回 (rc, 合并输出)。用于 clone 到尚未存在的目录。"""
    p = subprocess.run(argv, capture_output=True, text=True)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def is_repo(root):
    return os.path.isdir(os.path.join(root, ".git"))


# ---------------------------------------------------------------- 环境变量

ENV_TOKEN = "BACKUP_GIT_TOKEN"
ENV_REPO = "BACKUP_GIT_REPO"

ENV_NOTES = {
    ENV_TOKEN: "minis-git-backup 推送凭据，GitHub fine-grained token（Contents 读写）",
    ENV_REPO: "minis-git-backup 目标仓库，格式：作者名/仓库名",
}


def env_link(key):
    """生成填值的设置页深链：key 预填，值留空等用户填。"""
    from urllib.parse import quote
    return ("minis://settings/environments?create_key=%s&create_value=&create_note=%s"
            % (quote(key), quote(ENV_NOTES[key])))


def env_guide(missing):
    """缺失变量的引导文案：逐个列出用途与填值链接。"""
    lines = ["缺少环境变量，无法继续：", ""]
    for key in missing:
        lines.append("- %s：%s" % (key, ENV_NOTES[key]))
        lines.append("  %s" % env_link(key))
        lines.append("")
    lines.append("打开上面的链接，值留空，填入后保存即可（token 只存本机，不会进仓库）。")
    return "\n".join(lines)


def token():
    return os.environ.get(ENV_TOKEN, "").strip()


def repo_env():
    return os.environ.get(ENV_REPO, "").strip()


def authed_url(url, tok):
    """把 https://github.com/a/b.git 变成带 token 的地址，用于推送。"""
    if not tok or not url.startswith("https://"):
        return url
    rest = url[len("https://"):]
    if "@" in rest.split("/")[0]:
        return url
    return "https://x-access-token:%s@%s" % (tok, rest)


def mask(s, tok):
    return s.replace(tok, "***") if tok else s


def run_remote(root, url, tok, args):
    """用带 token 的 URL 跑一次远程操作，输出里抹掉 token。"""
    rc, out, err = git(root, *args[:1], authed_url(url, tok), *args[1:], check=False)
    return rc, mask(out, tok), mask(err, tok)


def explain_push_error(err):
    """把 git/GitHub 的常见拒绝翻译成可操作的提示。"""
    low = (err or "").lower()
    if "403" in low or "denied to" in low or "not accessible" in low:
        return ("token 没有该仓库的写权限。去 GitHub → Settings → Developer settings → "
                "Fine-grained tokens → 该 token：Repository access 勾上这个仓库，"
                "Permissions → Contents 设为 Read and write，然后重新保存")
    if "401" in low or "authentication failed" in low or "invalid username" in low:
        return "token 无效或已过期，重新生成并在设置里更新 %s" % ENV_TOKEN
    if "404" in low or "not found" in low:
        return "仓库不存在，或 token 的 Repository access 没有包含它；确认 %s 拼写" % ENV_REPO
    if "timed out" in low or "could not resolve" in low or "network" in low:
        return "网络不可达，检查网络连接后重试"
    return ""


def remote_owner_name(url):
    """从 https://github.com/<owner>/<repo>.git 取出 owner 与 repo。"""
    u = url.rstrip("/")
    if u.endswith(".git"):
        u = u[:-4]
    parts = u.replace(":", "/").split("/")
    if len(parts) < 2:
        return None
    return parts[-2], parts[-1]


def github_env():
    """读取 BACKUP_GIT_TOKEN 与 BACKUP_GIT_REPO；缺失或格式不对时一次列出全部问题。"""
    tok = token()
    repo = repo_env()
    missing, bad = [], []

    if not tok:
        missing.append(ENV_TOKEN)
    if not repo:
        missing.append(ENV_REPO)
    elif repo.count("/") != 1 or not all(p.strip() for p in repo.split("/")):
        bad.append("%s 格式应为 作者名/仓库名，当前是 %r" % (ENV_REPO, repo))

    if missing or bad:
        msg = []
        if missing:
            msg.append(env_guide(missing))
        if bad:
            msg.append("；".join(bad))
        raise Fail("\n".join(msg), RC_NO_TOKEN)

    owner, name = [p.strip() for p in repo.split("/")]
    return tok, owner, name


def is_network_url(url):
    """本地路径与 file:// 不参与一致校验（测试与离线演练用）。"""
    return url.startswith(("https://", "http://", "git@", "ssh://"))


def remote_matches(url, owner, name):
    got = remote_owner_name(url)
    if not got:
        return False
    return got[0].lower() == owner.lower() and got[1].lower() == name.lower()


def remote_url(root):
    rc, out, _ = git(root, "remote", "get-url", "origin", check=False)
    return out.strip() if rc == 0 else ""


def current_branch(root):
    rc, out, _ = git(root, "rev-parse", "--abbrev-ref", "HEAD", check=False)
    return out.strip() if rc == 0 and out.strip() != "HEAD" else "master"# ---------------------------------------------------------------- .git 改名

def find_git_parents(root):
    """找出所有含 `.git` 的目录（任意层级），不进入 `.git` 内部。

    跳过根目录自己的 `.git`（那是备份仓库本身）与 `bak/`（还原暂存）。
    返回父目录的绝对路径列表。
    """
    out = []
    skip_top = {STAGE_DIR}
    for dp, dns, fns in os.walk(root):
        rel = os.path.relpath(dp, root)
        if rel == ".":
            if ".git" in dns:
                dns.remove(".git")      # 备份仓库自己，永不改名
            continue
        if rel.split(os.sep)[0] in skip_top:
            dns[:] = []
            continue
        if HIDDEN_IGNORE in fns:
            dns[:] = []                 # 上次中断残留，不深入
            continue
        if HIDDEN_GIT in dns:
            dns.remove(HIDDEN_GIT)      # 上次中断残留，不深入
        if ".git" in dns:
            out.append(dp)
            dns.remove(".git")          # 不进入 .git，但继续找嵌套仓库
    return out


def find_ignore_parents(root):
    """找出除根目录外所有含 `.gitignore` 的目录，不进入 .git / .git-backup。

    这些 .gitignore 会作用于备份仓库（实测 `projects/a/.gitignore` 的 `/*/`
    能把嵌套仓库整个排掉），所以备份期间也要临时改名。
    根的 .gitignore 是脚本生成的，保留生效。
    """
    out = []
    for dp, dns, fns in os.walk(root):
        rel = os.path.relpath(dp, root)
        if rel == ".":
            continue
        if rel.split(os.sep)[0] == STAGE_DIR:
            dns[:] = []
            continue
        for hidden in (".git", HIDDEN_GIT):
            if hidden in dns:
                dns.remove(hidden)
        # 原名与备份名都算：恢复时找的是备份名，改名时找的是原名
        if IGNORE_NAME in fns or HIDDEN_IGNORE in fns:
            out.append(dp)
    return out


def hide_ignores(root):
    """把子目录的 .gitignore 改名成 .gitignore-backup，返回改名的目录。"""
    done = []
    for parent in find_ignore_parents(root):
        src = os.path.join(parent, IGNORE_NAME)
        dst = os.path.join(parent, HIDDEN_IGNORE)
        if not os.path.exists(src):
            continue
        if os.path.exists(dst):
            raise Fail("同名残留已存在，先处理它再备份：%s" % dst)
        os.rename(src, dst)
        done.append(parent)
    return done


def unhide_ignores(root):
    """把子目录的 .gitignore-backup 改回 .gitignore，返回改名的目录。"""
    done = []
    for parent in find_ignore_parents(root):
        src = os.path.join(parent, HIDDEN_IGNORE)
        dst = os.path.join(parent, IGNORE_NAME)
        if not os.path.isdir(src) and not os.path.exists(src):
            continue
        if os.path.exists(dst):
            continue                     # 已恢复过
        os.rename(src, dst)
        done.append(parent)
    return done


def hide_git_dirs(root):
    """把所有 `.git` 改名成 `.git-backup`，返回实际改名的父目录列表。

    改名后这些目录不再是 git 仓库，备份仓库可以把它们当普通文件跟踪。
    """
    done = []
    for parent in find_git_parents(root):
        src = os.path.join(parent, ".git")
        dst = os.path.join(parent, HIDDEN_GIT)
        if os.path.exists(dst):
            raise Fail("同名残留已存在，先处理它再备份：%s" % dst)
        os.rename(src, dst)
        done.append(parent)
    hide_ignores(root)
    return done


def unhide_git_dirs(root, parents):
    """把 `.git-backup` 改回 `.git`。任何情况下都要执行，用 finally 包住。"""
    for parent in parents:
        src = os.path.join(parent, HIDDEN_GIT)
        dst = os.path.join(parent, ".git")
        if os.path.isdir(src) and not os.path.exists(dst):
            os.rename(src, dst)
    unhide_ignores(root)


def heal_leftover(root):
    """上次异常中断可能留下 `.git-backup`：先改回 `.git`，让仓库恢复正常。"""
    fixed = []
    for dp, dns, fns in os.walk(root):
        rel = os.path.relpath(dp, root)
        if rel == ".":
            continue
        if rel.split(os.sep)[0] == STAGE_DIR:
            dns[:] = []
            continue
        if HIDDEN_IGNORE in fns:
            src = os.path.join(dp, HIDDEN_IGNORE)
            dst = os.path.join(dp, IGNORE_NAME)
            if not os.path.exists(dst):
                os.rename(src, dst)
                fixed.append(dp)
            fns.remove(HIDDEN_IGNORE)
        if HIDDEN_GIT in dns:
            src = os.path.join(dp, HIDDEN_GIT)
            dst = os.path.join(dp, ".git")
            if not os.path.exists(dst):
                os.rename(src, dst)
                fixed.append(dp)
            dns.remove(HIDDEN_GIT)
            continue
        if ".git" in dns:
            dns.remove(".git")
    return fixed


# ---------------------------------------------------------------- 隐私扫描

def memory_files(root):
    """memory/ 下所有 Markdown 文件。"""
    mdir = os.path.join(root, "memory")
    out = []
    if not os.path.isdir(mdir):
        return out
    for n in sorted(os.listdir(mdir)):
        if n.endswith(".md"):
            out.append(os.path.join(mdir, n))
    return out


def scan_memory(root, fix=False, quiet=False):
    """扫描 memory；fix=True 时就地打码。

    返回 (命中数, 需处理数, 已改写文件数, 报告行)。
    需处理数只统计 high/medium——low 只提示，不会改写。
    """
    import privacy

    total_hits, fixable, total_changed, lines = 0, 0, 0, []
    for path in memory_files(root):
        try:
            text = open(path, encoding="utf-8").read()
        except UnicodeDecodeError:
            continue
        hits = privacy.scan_text(text)
        if not hits:
            continue
        total_hits += len(hits)
        fixable += sum(1 for h in hits if h[2] in privacy.FIX_SEVERITY)
        if not quiet:
            lines.append("  %s" % os.path.basename(path))
            lines.extend(privacy.report(hits))
        if fix:
            new, changed = privacy.redact_text(text)
            if changed:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(new)
                total_changed += 1
    return total_hits, fixable, total_changed, lines


def cmd_scan(args, root):
    hits, fixable, changed, lines = scan_memory(root, fix=args.fix)
    if hits == 0:
        print("memory 干净，无需脱敏")
        return RC_OK
    print("memory 扫描：%d 处命中（其中 %d 处需脱敏，其余为低风险提示）" % (hits, fixable))
    for line in lines:
        print(line)
    if args.fix:
        if changed:
            print("已脱敏 %d 处（%d 个文件）" % (fixable, changed))
        else:
            print("无需脱敏的条目（命中的都是低风险提示）")
    else:
        print("未改动文件；要打码请加 --fix（backup 会自动做）")
    return RC_OK


# ---------------------------------------------------------------- 提交信息

SUBJECT_MAX = 50
COMMIT_TYPE = "chore"
COMMIT_SCOPE = "backup"


def check_message(msg):
    """校验提交标题是否符合 Angular 规则，返回问题列表（空表示合格）。"""
    import re as _re
    if not msg:
        return ["提交信息为空"]
    head = msg.splitlines()[0]
    if not _re.match(r"^[a-z]+(\([a-z0-9_-]+\))?: .+", head):
        return ["标题须为 `<类型>(<范围>): <主题>` 形式，类型小写"]
    typ = head.split("(")[0].split(":")[0]
    if typ not in ("feat", "fix", "docs", "test", "chore", "refactor", "perf"):
        return ["类型 `%s` 不在允许集合内" % typ]
    subject = head.split(": ", 1)[1]
    problems = []
    if len(subject) > SUBJECT_MAX:
        problems.append("标题 %d 字，超过 %d 字上限" % (len(subject), SUBJECT_MAX))
    if subject.endswith("。") or subject.endswith("."):
        problems.append("标题不要以句号结尾")
    return problems


def changed_paths(root):
    """git status 里所有改动路径（-z 解析，含重命名的新路径）。"""
    rc, out, _ = git(root, "status", "--porcelain", "-uall", "-z", check=False)
    raw = out.split("\0")
    paths = []
    i = 0
    while i < len(raw):
        rec = raw[i]
        if not rec.strip():
            i += 1
            continue
        code = rec[:2].strip()
        path = rec[3:]
        if code in ("R", "C"):
            i += 1
            path = raw[i] if i < len(raw) else path
        paths.append(path)
        i += 1
    return paths


def build_message(root):
    """按实际变动生成 Angular 规范的提交信息。

    标题只报类别与数量，明细放正文。返回 (title, detail) 或 None。
    """
    paths = changed_paths(root)
    if not paths:
        return None

    repos = {}      # 仓库路径 → 变动文件数
    files = {}      # 顶层目录 → 变动文件数
    for p in paths:
        parts = p.split("/")
        if HIDDEN_GIT in parts:
            i = parts.index(HIDDEN_GIT)
            repo = "/".join(parts[:i]) or "."
            repos[repo] = repos.get(repo, 0) + 1
        else:
            top = parts[0] if len(parts) > 1 else "(根目录)"
            files[top] = files.get(top, 0) + 1

    n_repo = len(repos)
    n_file = sum(files.values())
    bits = []
    if n_repo:
        bits.append("%d 个仓库" % n_repo)
    if n_file:
        bits.append("%d 个文件" % n_file)
    subject = "备份 " + "、".join(bits) if bits else "备份快照"
    while len(subject) > SUBJECT_MAX and len(bits) > 1:
        bits.pop()
        subject = "备份 " + "、".join(bits)
    title = "%s(%s): %s" % (COMMIT_TYPE, COMMIT_SCOPE, subject)

    detail = []
    proj = sorted(r for r in repos if r.startswith("projects/"))
    skill = sorted(r for r in repos if r.startswith("skills/"))
    other = sorted(set(repos) - set(proj) - set(skill))

    def line(label, items):
        if not items:
            return None
        shown = "、".join(items[:5])
        return "`" + label + "`：" + shown + (" 等" if len(items) > 5 else "")

    for d in [
        line("工程仓库", proj),
        line("技能仓库", skill),
        line("其他仓库", other),
        ("`文件`：" + "、".join("%s %d 个" % (k, v) for k, v in sorted(files.items())[:6])),
    ]:
        if d:
            detail.append(d)
    return title, detail# ---------------------------------------------------------------- 备份主流程

def ensure_identity(root):
    """克隆来的仓库可能缺 user.email，提交前补上本地身份。"""
    git(root, "config", "user.email", "agent@local", check=False)
    git(root, "config", "user.name", "Minis Agent", check=False)


def render_ignore():
    """生成 .gitignore：只排除本技能暂存区与可重建缓存。"""
    return "\n".join(IGNORE_LINES) + "\n"


def sync_ignore(root):
    """让 .gitignore 与当前规则一致，返回是否发生改写。"""
    path = os.path.join(root, ".gitignore")
    content = render_ignore()
    old = ""
    if os.path.exists(path):
        old = open(path, encoding="utf-8").read()
    if old == content:
        return False
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return True


def commit_and_push(root, args, hidden):
    """提交并推送。调用时 .git 已全部改名成 .git-backup。"""
    ensure_identity(root)
    git(root, "add", "-A")

    built = build_message(root)
    if built:
        title, detail = built
        msg = args.message or title
        if args.message:
            problems = check_message(args.message)
            if problems:
                raise Fail("-m 的提交信息不符合 Angular 规则：\n  " + "\n  ".join(problems))
        argv = ["commit", "-m", msg]
        if detail and not args.message:
            argv += ["-m", "\n".join(detail)]
        git(root, *argv)
        print("已提交：%s" % msg)
        for d in detail:
            print("  %s" % d)
    else:
        print("没有可提交的改动（内容与上次一致）")

    if args.local:
        print("已跳过推送（--local）")
        return

    push_with_check(root, args, hidden)


def prepare_sync(root, tok, url, branch):
    """推送前把远程取到本地仓库（不建临时目录），确认双方历史对得上。"""
    refspec = "+refs/heads/%s:refs/remotes/origin/%s" % (branch, branch)
    rc, out, err = git(root, "fetch", "--no-tags", authed_url(url, tok), refspec, check=False)
    out, err = mask(out, tok), mask(err, tok)
    if rc != 0:
        if "couldn't find remote ref" in (err or out) or "could not find remote ref" in (err or out):
            return True                  # 远程还没有这个分支（空仓库）
        msg = "拉取远程失败：%s" % (err or out)
        hint = explain_push_error(err or out)
        if hint:
            msg += "\n原因：%s" % hint
        raise Fail(msg)

    rc, remote_head, _ = git(root, "rev-parse", "--verify", "--quiet",
                             "refs/remotes/origin/%s" % branch, check=False)
    if rc != 0 or not remote_head:
        return True                      # 远程空仓库
    rc, local_head, _ = git(root, "rev-parse", "--verify", "--quiet",
                            "refs/heads/%s" % branch, check=False)
    if rc != 0 or not local_head:
        return True
    if local_head == remote_head:
        return True

    rc, _, _ = git(root, "merge-base", "--is-ancestor", remote_head, local_head, check=False)
    if rc == 0:
        return True                      # 远程是本地祖先 → 快进

    rc, _, _ = git(root, "merge-base", "--is-ancestor", local_head, remote_head, check=False)
    if rc == 0:
        raise Fail("远端有本地没有的提交（提交记录对不上），已终止推送；"
                   "先跑 backup.py restore 还原后再备份")
    raise Fail("本地与远端历史已分叉（提交记录对不上），已终止推送；"
               "先跑 backup.py restore 还原后再备份")


def tree_digest(base, rel_skip=(".git", STAGE_DIR, "__pycache__")):
    """算一棵目录树的指纹：{相对路径: (类型, 大小, 内容哈希)}。

    `.git` 不参与（二进制对象在前一步已单独校验）。用 sha256 而不是 mtime，
    因为 mtime 在跨文件系统复制时不可信。
    """
    import hashlib

    out = {}
    base = os.path.abspath(base)
    for dp, dns, fns in os.walk(base):
        rel_dir = os.path.relpath(dp, base)
        if rel_dir != ".":
            top = rel_dir.split(os.sep)[0]
            if top in rel_skip or ".git" in rel_dir.split(os.sep):
                dns[:] = []
                continue
        for n in sorted(fns):
            p = os.path.join(dp, n)
            rel = os.path.relpath(p, base)
            parts = rel.split(os.sep)
            if any(x in rel_skip for x in parts) or ".git" in parts:
                continue
            if n in rel_skip:
                continue
            if os.path.islink(p):
                out[rel] = ("link", os.readlink(p), "")
                continue
            try:
                size = os.path.getsize(p)
                h = hashlib.sha256()
                with open(p, "rb") as f:
                    for chunk in iter(lambda: f.read(1 << 20), b""):
                        h.update(chunk)
                out[rel] = ("file", size, h.hexdigest())
            except OSError as e:
                out[rel] = ("error", 0, str(e))
    return out


def compare_trees(local, remote):
    """比对两棵树，返回 (缺失, 多余, 内容不同) 三个列表。"""
    missing = sorted(set(local) - set(remote))
    extra = sorted(set(remote) - set(local))
    differ = sorted(k for k in set(local) & set(remote) if local[k] != remote[k])
    return missing, extra, differ


def verify_remote(root, url, tok, branch, hidden):
    """推送成功后克隆远程，逐项验证内容与本地一致。

    三道关，任一不过即判定推送失败：
      1. 能克隆、能还原 .git-backup
      2. 每个子仓库都能读出历史
      3. 文件树与本地逐字节一致（sha256 比对）

    hidden 是本次改名的父目录列表，用于把本地视图也还原成「未改名」再比。
    """
    stage = os.path.join(tempfile.mkdtemp(prefix="minis-verify-"), "repo")
    try:
        rc, out = run_proc(["git", "clone", "--depth", "1", "-b", branch,
                            authed_url(url, tok), stage])
        if rc != 0:
            return False, "克隆失败：%s" % mask(out, tok)

        if not os.path.isdir(os.path.join(stage, ".git")):
            return False, "克隆结果里没有 .git"

        n_git, n_ign = unhide_in_stage(stage)
        if n_git == 0:
            return False, "克隆结果里没有任何 .git-backup，备份是空的"

        # 子仓库能否读出历史
        broken = []
        for dp, dns, _ in os.walk(stage):
            if ".git" not in dns:
                continue
            dns.remove(".git")
            r, _, e = git(dp, "rev-parse", "--verify", "--quiet", "HEAD", check=False)
            if r != 0:
                broken.append((os.path.relpath(dp, stage), e))
        if broken:
            return False, "有 %d 个子仓库无法读取历史，例如 %s（%s）" % (
                len(broken), broken[0][0], broken[0][1])

        # 内容一致性：**以本地实际内容为基准**，检查克隆回来的内容是否完整覆盖本地。
        # 方向不能反：本地是「源」，远程是「副本」，缺什么都不行。
        # 比对前先把本地也造一份「未改名」视图，与远程的形态对齐。
        local_view = os.path.join(tempfile.mkdtemp(prefix="minis-localview-"), "v")
        try:
            shutil.copytree(root, local_view, symlinks=True,
                            ignore=shutil.ignore_patterns(".git", STAGE_DIR, "__pycache__"))
            hide_git_dirs(local_view)
            unhide_in_stage(local_view)

            local_digest = tree_digest(local_view, rel_skip=(".git", STAGE_DIR))
            remote_digest = tree_digest(stage, rel_skip=(".git", STAGE_DIR))

            # missing：本地有、远程没有 → 备份丢了内容，必须失败
            # extra  ：远程有、本地没有 → 远程残留旧文件，提示但不阻塞
            # differ ：两边都有但内容不同 → 备份不完整，必须失败
            missing, extra, differ = compare_trees(local_digest, remote_digest)
            if missing or differ:
                parts = []
                if missing:
                    parts.append("远程缺少 %d 个本地文件（如 %s）"
                                 % (len(missing), missing[0]))
                if differ:
                    parts.append("远程有 %d 个文件与本地内容不同（如 %s）"
                                 % (len(differ), differ[0]))
                return False, "内容比对不一致：" + "；".join(parts)
            if extra:
                print("  注意：远程有 %d 个本地没有的文件（如 %s），来自更早的备份"
                      % (len(extra), extra[0]))
        finally:
            shutil.rmtree(os.path.dirname(local_view), ignore_errors=True)

        return True, ("克隆验证通过：%d 个子仓库、%d 个 ignore 文件、"
                      "%d 个文件逐字节一致" % (n_git, n_ign, len(local_digest)))
    finally:
        shutil.rmtree(os.path.dirname(stage), ignore_errors=True)


def push_with_check(root, args, hidden):
    """推送 → 立刻克隆回来验证 → 验证失败则中止。

    只有「远程能被完整还原」才算推送成功，否则远程内容不可信。
    """
    tok, owner, name = github_env()
    url = args.remote or remote_url(root) or "https://github.com/%s/%s.git" % (owner, name)
    if not remote_url(root) and not args.remote:
        print("未配置 origin，按 %s 使用 %s" % (ENV_REPO, url))
    if os.environ.get("BACKUP_GIT_NO_NETWORK") == "1" and is_network_url(url):
        raise Fail("已设置 BACKUP_GIT_NO_NETWORK=1，拒绝推送到网络地址（%s）；"
                   "测试环境只允许 file:// 或本地路径" % url)
    if is_network_url(url) and not remote_matches(url, owner, name):
        raise Fail("推送地址 %s 与 %s=%s/%s 不匹配" % (url, ENV_REPO, owner, name))

    branch = current_branch(root)
    print("核对远端历史（%s）..." % branch)
    prepare_sync(root, tok, url, branch)

    rc, out, err = run_remote(root, url, tok, ["push", "--set-upstream", branch])
    if rc != 0:
        msg = "推送失败：%s" % (err or out)
        hint = explain_push_error(err or out)
        if hint:
            msg += "\n原因：%s" % hint
        raise Fail(msg)
    print("已推送：%s/%s/%s" % (owner, name, branch))

    print("回验：克隆远程检查内容是否与本地一致 ...")
    ok, note = verify_remote(root, url, tok, branch, hidden)
    if ok:
        print("回验通过：%s" % note)
    else:
        raise Fail("推送后回验失败：%s\n"
                   "远程内容不可信，请检查网络与 token 权限后重跑 backup" % note)


def cmd_backup(args, root):
    if not is_repo(root):
        raise Fail("备份仓库还没初始化：先跑 backup.py init", RC_NOT_INIT)
    if not (args.local or args.dry):
        github_env()        # 两个变量一次校验，缺什么一起告诉用户

    if not args.dry:
        if sync_ignore(root):
            print(".gitignore 已同步（只排除暂存区与缓存）")
        fixed = heal_leftover(root)
        if fixed:
            print("修复上次中断残留的 %d 个 .git-backup" % len(fixed))

    # 脱敏是提交的一部分：静默执行，推送后汇报
    hits, fixable, changed, lines = scan_memory(root, fix=not args.dry, quiet=True)

    if args.dry:
        parents = find_git_parents(root)
        print("将备份 %d 个仓库（.git → .git-backup）" % len(parents))
        for p in parents[:10]:
            print("  %s" % os.path.relpath(p, root))
        if len(parents) > 10:
            print("  … 共 %d 个" % len(parents))
        if fixable:
            print("预演发现 memory 有 %d 处需脱敏（实际提交时会自动打码）" % fixable)
        elif hits:
            print("预演发现 memory 有 %d 处低风险提示，不会改动" % hits)
        print("（预演，未提交、未改名）")
        return RC_OK

    if fixable:
        print("提交前已脱敏 %d 处（%d 个文件）" % (fixable, changed))
    elif hits:
        print("memory 有 %d 处低风险提示（公网地址等），未改动" % hits)

    parents = find_git_parents(root)
    hidden = hide_git_dirs(root)
    print("已改名 %d 个 .git → %s" % (len(hidden), HIDDEN_GIT))
    try:
        commit_and_push(root, args, hidden)
    finally:
        unhide_git_dirs(root, hidden)
        print("已恢复 %d 个 %s → .git" % (len(hidden), HIDDEN_GIT))

    if hits:
        print("脱敏清单（只显示打码后的片段）：")
        for line in lines:
            print(line)
    return RC_OK


def cmd_init(args, root):
    """只初始化本地仓库：不设远程、不联网、不碰 token。"""
    created = []
    gignore = os.path.join(root, ".gitignore")
    content = render_ignore()
    if os.path.exists(gignore):
        old = open(gignore, encoding="utf-8").read()
        if old == content:
            print(".gitignore 已是正确内容")
        elif args.dry:
            print("将更新 .gitignore")
        else:
            with open(gignore, "w", encoding="utf-8") as f:
                f.write(content)
            created.append(".gitignore（更新）")
    else:
        if args.dry:
            print("将写入 .gitignore")
        else:
            with open(gignore, "w", encoding="utf-8") as f:
                f.write(content)
            created.append(".gitignore")

    if not is_repo(root):
        print("将在 %s 初始化 git 仓库" % root)
        if not args.dry:
            git(root, "init", "-q")
            git(root, "config", "user.name", "Minis Agent", check=False)
            git(root, "config", "user.email", "agent@local", check=False)
            created.append(".git/")
    else:
        print("仓库已存在：%s" % root)

    print("已创建：%s" % (", ".join(created) if created else "无（已是最新）"))
    print("本地仓库就绪；要推送请在本地提交并推送（本技能 backup 命令会自动推送）")
    return RC_OK


def cmd_remote(args, root):
    """查看或设置远程地址，并验证可达性。"""
    if not is_repo(root):
        raise Fail("备份仓库还没初始化：先跑 backup.py init", RC_NOT_INIT)
    if args.show or not args.url:
        url = remote_url(root)
        print("origin = %s" % (url or "（未配置）"))
        repo = repo_env()
        if repo and "/" in repo:
            print("%s = %s → https://github.com/%s.git" % (ENV_REPO, repo, repo))
        return RC_OK
    if not args.url:
        repo = repo_env()
        if not repo:
            raise Fail("缺少 --url，也未设置 %s\n%s" % (ENV_REPO, env_guide([ENV_REPO])))
        args.url = "https://github.com/%s.git" % repo
    if args.dry:
        print("将设置 origin = %s" % args.url)
        return RC_OK
    if remote_url(root):
        git(root, "remote", "set-url", "origin", args.url)
    else:
        git(root, "remote", "add", "origin", args.url)
    print("已设置 origin = %s" % args.url)
    tok = token()
    if not tok:
        print("未设置 %s，推送时会被拒绝" % ENV_TOKEN)
        return RC_OK
    rc, out, err = run_remote(root, args.url, tok, ["ls-remote", "--heads"])
    if rc == 0:
        print("远程可访问：%s" % (out.splitlines()[0] if out else "（空仓库）"))
    else:
        print("远程无法访问：%s" % (err or out))
    return RC_OK# ---------------------------------------------------------------- 还原

def human_stamp():
    """给人看又不必转义的目录名：2026-11-24_14-33。"""
    import datetime
    return datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")


def business_entries(root):
    """挂载根里除本技能暂存目录之外的条目。"""
    return [n for n in sorted(os.listdir(root)) if n != STAGE_DIR]


def guard_restore_target(root):
    """还原前判断本地状态，决定用哪种还原方式。

    返回 "repo"（本地顶层有 .git，走 bak/ 保护流程）
      或 "empty"（本地无 .git 且目录为空，直接整份铺入，不需要 bak/）
    本地无 .git 但目录非空时抛 Fail(RC_NEED_CONFIRM)。
    """
    if is_repo(root):
        return "repo"
    entries = business_entries(root)
    if not entries:
        return "empty"
    raise Fail(
        "本地顶层没有 .git，目录里却有 %d 个条目：%s\n"
        "直接还原会覆盖它们，所以先停下，请你决定下一步：\n"
        "  1) 手工把这些内容移走，然后重跑 restore —— 本次会整份铺入备份\n"
        "  2) 跑 backup.py init 建一个本地空仓库，再跑 backup 稍后上传\n"
        "  3) 确认这些内容可以丢弃时，自己删空目录再重跑 restore"
        % (len(entries), "、".join(entries[:6]) + (" 等" if len(entries) > 6 else "")),
        RC_NEED_CONFIRM)


def move_to_bak(root):
    """把根目录除 bak/ 外的所有条目移进 bak/<时间戳>/，返回 (目录, 条目数)。"""
    bak = os.path.join(root, STAGE_DIR)
    os.makedirs(bak, exist_ok=True)
    stamp_dir = os.path.join(bak, human_stamp())
    n = 1
    while os.path.exists(stamp_dir):
        n += 1
        stamp_dir = os.path.join(bak, "%s_%d" % (human_stamp(), n))
    os.makedirs(stamp_dir)

    moved = 0
    for name in sorted(os.listdir(root)):
        if name == STAGE_DIR:
            continue
        src = os.path.join(root, name)
        dst = os.path.join(stamp_dir, name)
        try:
            os.rename(src, dst)
        except OSError:
            if os.path.isdir(src) and not os.path.islink(src):
                shutil.copytree(src, dst, symlinks=True)
                shutil.rmtree(src, ignore_errors=True)
            else:
                shutil.copy2(src, dst, follow_symlinks=False)
                os.remove(src)
        moved += 1
    return stamp_dir, moved


def restore_into_root(stage, root):
    """把 stage 里的全部条目移回挂载根。"""
    moved = 0
    for name in sorted(os.listdir(stage)):
        if name == STAGE_DIR:
            continue
        src = os.path.join(stage, name)
        dst = os.path.join(root, name)
        if os.path.isdir(dst) and not os.path.islink(dst):
            shutil.rmtree(dst, ignore_errors=True)
        elif os.path.exists(dst):
            os.remove(dst)
        try:
            os.rename(src, dst)
        except OSError:
            if os.path.isdir(src) and not os.path.islink(src):
                shutil.copytree(src, dst, symlinks=True)
            else:
                shutil.copy2(src, dst, follow_symlinks=False)
        moved += 1
    return moved


def unhide_in_stage(stage):
    """把 stage 里的 .git-backup / .gitignore-backup 全部改回原名。

    返回 (恢复的子仓库数, 恢复的 ignore 文件数)。
    """
    git_parents = []
    for dp, dns, _ in os.walk(stage):
        if dp == stage:
            continue
        if HIDDEN_GIT in dns:
            git_parents.append(dp)
            dns.remove(HIDDEN_GIT)
    for parent in git_parents:
        src = os.path.join(parent, HIDDEN_GIT)
        dst = os.path.join(parent, ".git")
        if not os.path.exists(dst):
            os.rename(src, dst)
    ign = unhide_ignores(stage)
    return len(git_parents), len(ign)


def cmd_restore(args, root):
    """从远程拉回备份并还原到挂载根。"""
    tok, owner, name = github_env()
    url = args.remote or remote_url(root) or "https://github.com/%s/%s.git" % (owner, name)
    if os.environ.get("BACKUP_GIT_NO_NETWORK") == "1" and is_network_url(url):
        raise Fail("已设置 BACKUP_GIT_NO_NETWORK=1，拒绝从网络地址还原（%s）" % url)
    if is_network_url(url) and not remote_matches(url, owner, name):
        raise Fail("还原地址 %s 与 %s=%s/%s 不匹配" % (url, ENV_REPO, owner, name))

    mode = guard_restore_target(root)

    stage = tempfile.mkdtemp(prefix="minis-restore-")
    try:
        print("克隆到临时目录 %s ..." % stage)
        rc, out, err = git(stage, "clone", "--depth", "1", authed_url(url, tok), ".", check=False)
        if rc != 0:
            msg = "克隆失败：%s" % mask(err or out, tok)
            hint = explain_push_error(err or out)
            if hint:
                msg += "\n原因：%s" % hint
            raise Fail(msg)

        n_git, n_ign = unhide_in_stage(stage)
        print("已恢复 %d 个子仓库（%s → .git）、%d 个 %s → .gitignore"
              % (n_git, HIDDEN_GIT, n_ign, HIDDEN_IGNORE))

        if mode == "repo":
            bak_dir, moved = move_to_bak(root)
            print("原目录 %d 个条目已移入：%s" % (moved, bak_dir))
        else:
            print("本地为空且无 .git，直接整份铺入，不需要 bak/")

        n = restore_into_root(stage, root)
        print("备份已铺回根目录：%d 个条目" % n)

        if args.dry:
            print("（预演结束；要真正还原请去掉 --dry）")
            return RC_OK
        print("还原完成：%s" % root)
        if mode == "repo":
            print("原文件保留在 %s，确认无误后可自行删除" % bak_dir)
        return RC_OK
    finally:
        shutil.rmtree(stage, ignore_errors=True)


# ---------------------------------------------------------------- CLI

def build_parser():
    p = argparse.ArgumentParser(prog="backup.py", description="Minis 挂载目录的 GitHub 备份")
    p.add_argument("--version", action="version", version="minis-git-backup " + VERSION)
    p.add_argument("--mount", help="挂载目录（默认 /var/minis/mounts/Minis）")
    sub = p.add_subparsers(dest="cmd")

    i = sub.add_parser("init", help="初始化本地备份仓库（不联网）")
    i.add_argument("--dry", action="store_true", help="只预演")

    rm = sub.add_parser("remote", help="查看或设置远程仓库地址")
    rm.add_argument("--url", help="GitHub 仓库地址")
    rm.add_argument("--show", action="store_true", help="只打印当前地址")
    rm.add_argument("--dry", action="store_true", help="只预演")

    b = sub.add_parser("backup", help="改名 → 提交 → 推送 → 改回")
    b.add_argument("--local", action="store_true", help="只本地提交，不推送")
    b.add_argument("--dry", action="store_true", help="只预演，不改名不提交")
    b.add_argument("-m", "--message", help="提交信息（须符合 Angular 规范）")
    b.add_argument("--remote", help="覆盖推送地址（默认取 origin）")

    sc = sub.add_parser("scan", help="扫描 memory 的敏感信息")
    sc.add_argument("--fix", action="store_true", help="就地打码")

    r = sub.add_parser("restore", help="从远程下载并还原到挂载根")
    r.add_argument("--remote", help="远程地址（默认取 origin）")
    r.add_argument("--dry", action="store_true", help="只预演")
    return p


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        return RC_USAGE
    if getattr(args, "mount", None):
        os.environ[MOUNT_ENV] = args.mount
    try:
        root = mount_root()
        handler = {
            "init": cmd_init,
            "remote": cmd_remote,
            "backup": cmd_backup,
            "scan": cmd_scan,
            "restore": cmd_restore,
        }.get(args.cmd)
        if handler is None:
            return RC_USAGE
        return handler(args, root)
    except Fail as e:
        print("错误：%s" % e)
        return e.rc
    except KeyboardInterrupt:
        return RC_FAIL


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))