#!/usr/bin/env python3
"""deepseek-stack-workflow 状态机。

显式调用的工作流记录工具，不是工具调用拦截器。
状态文件：.state/turn-<id>.json，当前轮次指针：.state/current

固定命令（按顺序执行，不要改参数名）：
    python scripts/workflow.py start
    python scripts/workflow.py read ds-help
    python scripts/workflow.py route <技能名>
    python scripts/workflow.py read <技能名>
    python scripts/workflow.py plan <步骤1> [<步骤2> ...]
    python scripts/workflow.py run [--allow-fail] <命令>
    python scripts/workflow.py check
    python scripts/workflow.py verify
    python scripts/workflow.py stop

技能名两种来源，自动识别：
    references/ds-*.md            上游原文，记作 internal
    /var/minis/skills/<名>/SKILL.md   已安装的其他技能，记作 external

卡片标题按来源区分，外部技能必须标出来：
    内部：路由到 ds-xxx：读原文
    外部：路由到 yyy（外部skill）：读原文

方法层用 ds-*，领域层用外部技能，两者可以同时 route，
记录里用 source 区分，互不覆盖。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REFS = ROOT / "references"
STATE = Path(os.environ.get("WORKFLOW_STATE_DIR", str(ROOT / ".state")))

# 正常流程；BLOCKED / FAILED 可从任意未完成状态进入
ORDER = [
    "ROUTE_PENDING",
    "ROUTE_DONE",
    "READ_PENDING",
    "READ_DONE",
    "EXECUTING",
    "EXECUTED",
    "VERIFYING",
    "VERIFIED",
    "COMPLETED",
]
TERMINAL_BAD = {"BLOCKED", "FAILED"}


class Denied(Exception):
    """状态迁移不被允许。"""


EXTERNAL_DIRS = tuple(
    Path(x) for x in os.environ.get(
        "WORKFLOW_SKILLS_DIRS", "/var/minis/skills:/var/minis/mounts/Minis/skills"
    ).split(":") if x
)


SESSION_STUB = os.environ.get("WORKFLOW_SESSION_STUB")


def _stub() -> dict:
    if not SESSION_STUB:
        return {}
    try:
        return json.loads(Path(SESSION_STUB).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def session_total() -> int | None:
    """本会话消息总数，取不到（沙盒/无 CLI）返回 None。"""
    stub = _stub()
    if stub:
        return stub.get("total")
    try:
        r = subprocess.run(
            ["minis-sessions-cli", "messages", "--limit", "1"],
            capture_output=True, text=True, timeout=20,
        )
        if r.returncode != 0:
            return None
        return int(json.loads(r.stdout)["data"]["total"])
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return None


def session_commands(start: int, end: int) -> list[tuple[str, str]]:
    """取会话里 [start, end) 之间的 (命令, 卡片标题)。"""
    stub = _stub()
    if stub:
        return [(c, "") if isinstance(c, str) else (c["cmd"], c.get("title", ""))
                for c in stub.get("commands") or []]
    try:
        r = subprocess.run(
            ["minis-sessions-cli", "messages", "--tools",
             "--offset", str(start), "--limit", str(min(end - start, 100))],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            return []
        msgs = json.loads(r.stdout)["data"]["messages"]
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return []
    out = []
    for m in msgs:
        for c in m.get("tool_calls") or []:
            if c.get("name") != "shell_execute":
                continue
            try:
                payload = json.loads(c["input"])
                cmd = payload.get("command", "")
                title = payload.get("tool_title", "")
            except (ValueError, KeyError, TypeError):
                continue
            if cmd:
                out.append((cmd, title))
    return out


def parse_segments(cmd: str) -> tuple[list[str], list[str]]:
    """把一条 shell 命令拆成（workflow.py 调用, 其他命令）。

    先按行，再按 `&&` 拆；每段单独判定。
    `cd` / `export` / 注释放行——注意 `cd X && sed ...` 会被拆成两段，
    后一段仍然要检查，不能靠整行以 cd 开头就整体放行。
    """
    wf, others = [], []
    for raw in cmd.splitlines():
        # `workflow.py run "..."` 里可能含 && 和 ;，整行交给 run 记账，不再拆
        if "workflow.py run" in raw:
            wf.append(raw.strip())
            continue
        for part in raw.split("&&"):
            line = part.strip()
            if not line or line.startswith("#"):
                continue
            if "workflow.py" in line:
                wf.append(line)
            elif line.startswith(("cd ", "export ")):
                continue
            else:
                others.append(line)
    return wf, others


def norm_cmd(cmd: str) -> str:
    """归一化：只留最后一段、去掉管道与重定向，用来判断是否已记账。"""
    tail = cmd.split("&&")[-1].strip()
    tail = tail.split("|")[0].replace("2>&1", "").replace("2>/dev/null", "")
    return " ".join(tail.split())


def check_titles(cmd: str, title: str, data: dict | None = None) -> list[str]:
    """卡片标题必须和命令里的技能对得上：read/route 了谁，标题就得有谁。"""
    bad = []
    done = {r["skill"] for r in (data or {}).get("reads", [])}
    pairs = re.findall(r"workflow\.py\s+(read|route)\s+([\w.-]+)", cmd)
    reads = [s for sub, s in pairs if sub == "read"]
    if len(reads) > 1 and all(s in done for s in reads):
        bad.append(f"一次调用读了 {len(reads)} 个技能（{', '.join(reads)}），卡片只能显示一个标题，拆开调用")
    for sub, skill in pairs:
        if sub != "read":
            continue  # route 常与 read 合并成一次调用，只校验读取
        if skill not in title:
            bad.append(f"{sub} {skill} → 标题「{title}」缺技能名")
            continue
        if (REFS / f"{skill}.md").is_file() is False and "外部" not in title:
            bad.append(f"{sub} {skill} 是外部技能 → 标题「{title}」没标（外部skill）")
    if re.search(r"workflow\.py\s+start", cmd) and title != "创建工作流记录":
        bad.append(f"start 的标题应为「创建工作流记录」，实际「{title}」")
    if re.search(r"workflow\.py\s+plan", cmd) and title != "路径规划":
        bad.append(f"plan 的标题应为「路径规划」，实际「{title}」")
    return bad


def unlogged_commands(data: dict) -> list[str]:
    """本轮会话里跑过、但不是 workflow.py 调用、也没被 run 记过的命令。"""
    base = data.get("baseline_total")
    total = session_total()
    if base is None or total is None or total <= base:
        return []
    recorded = {norm_cmd(e["cmd"]) for e in data["executions"]}
    bad = []
    for cmd, title in session_commands(base, total):
        wf, others = parse_segments(cmd)
        if others:
            bad.extend(o for o in others if norm_cmd(o) not in recorded)
        elif not wf and norm_cmd(cmd) not in recorded:
            bad.append(cmd.splitlines()[0][:100])
        if wf and title:
            bad.extend(check_titles(cmd, title, data))
    return bad


def resolve_skill(skill: str) -> tuple[Path | None, str]:
    """返回 (原文路径, 来源)。references 优先，其次已安装技能目录。"""
    local = REFS / f"{skill}.md"
    if local.is_file():
        return local, "internal"
    for base in EXTERNAL_DIRS:
        cand = base / skill / "SKILL.md"
        if cand.is_file():
            return cand, "external"
    return None, ""


def current_session_id() -> str | None:
    """当前聊天的 session_id：会话隔离的依据。"""
    stub = _stub()
    if stub:
        return stub.get("session_id")
    try:
        r = subprocess.run(["minis-sessions-cli", "messages", "--limit", "1"],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return None
        return json.loads(r.stdout)["data"]["session_id"]
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return None


def latest_user_msg_id() -> str | None:
    """最新一条 user 消息的 id：用来判断本轮有没有被新消息取代。"""
    stub = _stub()
    if stub:
        return stub.get("last_user_msg_id")
    try:
        r = subprocess.run(["minis-sessions-cli", "messages", "--limit", "1"],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return None
        total = json.loads(r.stdout)["data"]["total"]
        r = subprocess.run(
            ["minis-sessions-cli", "messages", "--offset", str(max(total - 30, 0)),
             "--limit", "30"],
            capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return None
        msgs = json.loads(r.stdout)["data"]["messages"]
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return None
    for m in reversed(msgs):
        # 真正的用户消息带正文；tool_result 也是 role=user，必须排除
        if m.get("role") == "user" and (m.get("text") or "").strip() \
                and not (m.get("text") or "").startswith("[Tool result") \
                and not (m.get("tool_results") or []):
            return m.get("message_id")
    return None


def ptr_for(sid: str | None) -> Path:
    """每个会话一个指针文件，两个聊天互不覆盖。"""
    return STATE / f"current-{(sid or 'nosid')[:8]}"


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def die(msg: str, code: int = 1) -> None:
    print(f"拒绝：{msg}", file=sys.stderr)
    sys.exit(code)


def turn_path(turn_id: str) -> Path:
    return STATE / f"turn-{turn_id}.json"


def load_current() -> tuple[str, dict]:
    ptr = ptr_for(current_session_id())
    if not ptr.is_file():
        die("本轮还没有 start。先跑 python scripts/workflow.py start", 3)
    turn_id = ptr.read_text(encoding="utf-8").strip()
    p = turn_path(turn_id)
    if not p.is_file():
        die(f"状态文件丢失：{p}", 3)
    data = json.loads(p.read_text(encoding="utf-8"))
    return turn_id, data


def save(turn_id: str, data: dict) -> None:
    data["updated_at"] = now()
    turn_path(turn_id).write_text(
        json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )


def require(data: dict, allowed: set[str], action: str) -> None:
    cur = data["status"]
    if cur in TERMINAL_BAD:
        die(f"本轮已是 {cur}，不能再 {action}。修好问题后重新 start 一轮", 4)
    if cur not in allowed:
        die(
            f"当前状态 {cur} 不允许 {action}；需要 {' 或 '.join(sorted(allowed))}",
            4,
        )


# ---------- 命令 ----------


def session_texts(start: int, end: int) -> list[str]:
    """取会话里 [start, end) 之间助手消息的正文。"""
    stub = _stub()
    if stub:
        return list(stub.get("texts") or [])
    try:
        r = subprocess.run(
            ["minis-sessions-cli", "messages", "--tools",
             "--offset", str(start), "--limit", str(min(end - start, 100))],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            return []
        msgs = json.loads(r.stdout)["data"]["messages"]
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return []
    return [m["text"] for m in msgs if m.get("role") == "assistant" and m.get("text")]


def session_calls(start: int, end: int) -> list[dict]:
    """按时间顺序取 [start, end) 之间的工具调用：{name, cmd, title}。"""
    stub = _stub()
    if stub:
        if "calls" not in stub:
            return []  # 老沙盒没声明调用顺序，跳过时序检查
        return [{"name": c.get("name", ""), "cmd": c.get("cmd", ""),
                 "title": c.get("title", "")} for c in stub["calls"]]
    try:
        r = subprocess.run(
            ["minis-sessions-cli", "messages", "--tools",
             "--offset", str(start), "--limit", str(min(end - start, 100))],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            return []
        msgs = json.loads(r.stdout)["data"]["messages"]
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return []
    out = []
    for m in msgs:
        for c in m.get("tool_calls") or []:
            payload = {}
            try:
                payload = json.loads(c.get("input") or "{}")
            except (ValueError, TypeError):
                pass
            out.append({
                "name": c.get("name", ""),
                "cmd": payload.get("command", ""),
                "title": payload.get("tool_title", ""),
            })
    return out


def first_call_problem(data: dict) -> list[str]:
    """本轮第一个工具调用必须是 workflow.py start。

    窗口可能从 start 之后才开始（会话编号语义不保证），所以不假设 start 一定在窗口首条：
    找到 start 的位置，只看它前面有没有东西；窗口里没有 start 就无从判断，放行。
    """
    base = data.get("baseline_total")
    total = session_total()
    if base is None or total is None:
        return []
    calls = session_calls(base, total)
    if not calls:
        return []
    idx = None
    for i, c in enumerate(calls):
        if c["name"] == "shell_execute" and re.search(
                r"workflow\.py\s+(start|report|status|check)", c["cmd"]):
            idx = i
            break
    if idx is None:
        return []
    if idx == 0:
        return []
    first = calls[0]
    return [f"第一个工具调用不是 start，而是 {first['name']}「{first['title'] or first['cmd'][:40]}」"]


def last_user_index() -> int | None:
    """最后一条用户消息在会话里的位置：审计窗口要从这里开始，而不是从 start。"""
    stub = _stub()
    if stub:
        return stub.get("last_user_index", stub.get("total"))
    try:
        r = subprocess.run(["minis-sessions-cli", "messages", "--limit", "1"], capture_output=True,
                           text=True, timeout=30)
        if r.returncode != 0:
            return None
        total = json.loads(r.stdout)["data"]["total"]
        r = subprocess.run(
            ["minis-sessions-cli", "messages", "--offset", str(max(total - 30, 0)),
             "--limit", "30"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            return None
        msgs = json.loads(r.stdout)["data"]["messages"]
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return None
    base = max(total - 30, 0)
    for i in range(len(msgs) - 1, -1, -1):
        if msgs[i].get("role") == "user":
            return base + i
    return None


def session_texts_after(anchor_id: str | None, back: int = 300) -> list[str]:
    """从锚点消息往后，所有助手正文。锚点找不到就退化为最近 back 条。"""
    stub = _stub()
    if stub:
        return list(stub.get("texts") or [])
    try:
        r = subprocess.run(["minis-sessions-cli", "messages", "--limit", "1"],
                           capture_output=True, text=True, timeout=30)
        total = json.loads(r.stdout)["data"]["total"]
        start = max(total - back, 0)
        r = subprocess.run(
            ["minis-sessions-cli", "messages", "--offset", str(start),
             "--limit", str(total - start)],
            capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return []
        msgs = json.loads(r.stdout)["data"]["messages"]
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return []
    idx = 0
    if anchor_id:
        for i, m in enumerate(msgs):
            if m.get("message_id") == anchor_id:
                idx = i + 1
                break
    return [m["text"] for m in msgs[idx:]
            if m.get("role") == "assistant" and (m.get("text") or "").strip()]


def plan_missing_in_text(prev: dict) -> list[str]:
    """上一轮的计划，是否原样出现在助手正文里。"""
    plan = prev.get("plan") or []
    if not plan:
        return []
    cursor = prev.get("plan_cursor")
    texts = (session_texts(cursor, session_total())
             if cursor is not None and session_total() is not None
             else session_texts_after(prev.get("anchor_msg_id")))
    joined = norm_text("\n".join(texts))
    return [f"{p['n']}. {p['step']}" for p in plan
            if norm_text(p["step"]) not in joined]


def norm_text(s: str) -> str:
    """去掉反引号、空白与标点，用来比对正文里有没有贴计划。"""
    return re.sub(r"[`\s，。、；：！？,.;:!?()（）\[\]【】<>《》\-—…·]+", "", s)


def cmd_abandon(args: list[str]) -> int:
    """关闭一个被中断的轮次：状态置 ABANDONED 并记原因，历史不留悬空。"""
    reason = args[0] if args else ""
    if not reason:
        die('用法：abandon "<中断原因>"', 2)
    turn_id, data = load_current()
    if data["status"] in ("COMPLETED", "ABANDONED"):
        die(f"本轮已是 {data['status']}，无需 abandon", 4)
    data["status"] = "ABANDONED"
    data["completion"] = {"result": "abandoned", "reason": reason, "at": now()}
    save(turn_id, data)
    print(f"已放弃：{turn_id}（{reason}）")
    return 0


def cmd_start(args: list[str]) -> int:
    STATE.mkdir(parents=True, exist_ok=True)
    ptr = ptr_for(current_session_id())
    if ptr.is_file():
        prev_id = ptr.read_text(encoding="utf-8").strip()
        prev_file = turn_path(prev_id)
        if prev_file.is_file():
            prev = json.loads(prev_file.read_text(encoding="utf-8"))
            if prev.get("status") not in ("COMPLETED", "FAILED", "BLOCKED", "ABANDONED"):
                # 同会话里被新消息取代：自动收尾，不劳用户动手
                prev["status"] = "ABANDONED"
                prev["completion"] = {
                    "result": "abandoned",
                    "reason": "被新消息取代，未通过验收",
                    "at": now(),
                }
                prev_file.write_text(
                    json.dumps(prev, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"自动收尾：上一轮 {prev_id} 判为 ABANDONED（未验收就被新消息取代）",
                      file=sys.stderr)
    sid = current_session_id()
    turn_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    data = {
        "turn_id": turn_id,
        "session_id": sid,
        "anchor_msg_id": latest_user_msg_id(),
        "status": "ROUTE_PENDING",
        "baseline_total": last_user_index() or session_total(),
        "created_at": now(),
        "updated_at": now(),
        "routes": [],
        "reads": [],
        "plan": [],
        "executions": [],
        "verifications": [],
        "blockers": [],
        "failures": [],
        "completion": None,
    }
    save(turn_id, data)
    ptr_for(sid).write_text(turn_id, encoding="utf-8")
    ptr_for(current_session_id()).write_text(turn_id, encoding="utf-8")
    print(f"turn_id: {turn_id}")
    print(f"status:  ROUTE_PENDING")
    print(f"file:    {turn_path(turn_id)}")
    return 0


def cmd_route(args: list[str]) -> int:
    if not args:
        die("用法：route <技能名>", 2)
    skill = args[0]
    path, source = resolve_skill(skill)
    if path is None:
        die(f"找不到技能：{skill}（references/ 和 /var/minis/skills/ 都没有）", 2)
    turn_id, data = load_current()
    require(data, {"ROUTE_PENDING", "ROUTE_DONE", "READ_PENDING", "READ_DONE"}, "route")
    if "ds-help" not in {r["skill"] for r in data["reads"]}:
        die("本轮还没读取 ds-help.md，先跑：workflow.py read ds-help", 4)
    if any(r["skill"] == skill for r in data["routes"]):
        print(f"已记录过：{skill}（跳过重复）")
        return 0
    prev = data["status"]
    data["routes"].append({"skill": skill, "source": source, "at": now()})
    # 读过程中追加的技能要重新进入待读；尚未开始读的，停在 ROUTE_DONE
    data["status"] = "READ_PENDING" if prev in ("READ_PENDING", "READ_DONE") else "ROUTE_DONE"
    save(turn_id, data)
    print(f"记录路由：{skill}（{source}）")
    print(f"status:  {data['status']}")
    return 0


def cmd_read(args: list[str]) -> int:
    if not args:
        die("用法：read <技能名>", 2)
    skill = args[0]
    turn_id, data = load_current()
    if skill == "ds-help":
        require(data, {"ROUTE_PENDING", "ROUTE_DONE", "READ_PENDING", "READ_DONE"}, "read")
    else:
        require(data, {"ROUTE_DONE", "READ_PENDING", "READ_DONE"}, "read")
        if not any(r["skill"] == skill for r in data["routes"]):
            die(f"{skill} 不在本轮 routes 里，先 route {skill}", 4)
    path, source = resolve_skill(skill)
    if path is None:
        data.setdefault("failures", []).append(
            {"what": "read", "skill": skill, "error": "文件不存在", "at": now()}
        )
        data["status"] = "FAILED"
        save(turn_id, data)
        die(f"原文不存在：{path}", 5)
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    headings = [l.strip() for l in text.splitlines() if l.startswith("## ")][:6]
    entry = {
        "skill": skill,
        "path": str(path),
        "source": source,
        "bytes": len(raw),
        "lines": text.count("\n") + 1,
        "md5": hashlib.md5(raw).hexdigest(),
        "headings": headings,
        "summary": " ".join(text.split())[:200],
        "at": now(),
        "result": "ok",
    }
    data["reads"] = [r for r in data["reads"] if r["skill"] != skill]
    data["reads"].append(entry)
    pending = [r["skill"] for r in data["routes"] if r["skill"] not in {x["skill"] for x in data["reads"]}]
    if not data["routes"]:
        data["status"] = "ROUTE_PENDING"
    else:
        data["status"] = "READ_DONE" if not pending else "READ_PENDING"
    save(turn_id, data)
    # 全文打印：读取动作和看到的内容是同一次调用，杜绝「只读片段却记录全文」
    print(f"----- {path.name} 全文 {entry['lines']} 行 -----")
    print(text, end="" if text.endswith("\n") else "\n")
    print(f"----- 全文结束 md5 {entry['md5'][:8]} · {source} -----")
    print(f"status:  {data['status']}" + (f"（待读：{', '.join(pending)}）" if pending else ""))
    return 0


def cmd_run(args: list[str]) -> int:
    if not args:
        die("用法：run <命令>", 2)
    allow_fail = "--allow-fail" in args
    args = [a for a in args if a != "--allow-fail"]
    if not args:
        die("用法：run [--allow-fail] <命令>", 2)
    cmd = " ".join(args)
    turn_id, data = load_current()
    require(data, {"READ_DONE", "EXECUTING", "EXECUTED"}, "run")
    started = time.time()
    try:
        proc = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=900, cwd=ROOT
        )
        code, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        code, out, err = 124, "", "timeout"
    entry = {
        "cmd": cmd,
        "exit": code,
        "stdout_tail": out.strip().splitlines()[-20:],
        "stderr_tail": err.strip().splitlines()[-20:],
        "seconds": round(time.time() - started, 2),
        "allowed_fail": allow_fail,
        "at": now(),
    }
    data["executions"].append(entry)
    # 重做后销账：这条命令原来被判越界，现在记账了就不再算违规
    if data.get("violations"):
        data["violations"] = [
            v for v in data["violations"] if cmd not in v and v not in cmd
        ]
    ok = code == 0 or allow_fail
    data["status"] = "EXECUTED" if ok else "FAILED"
    if code != 0 and not allow_fail:
        data.setdefault("failures", []).append(
            {"what": "run", "cmd": cmd, "exit": code, "at": now()}
        )
    save(turn_id, data)
    print(out.rstrip())
    if err.strip():
        print(err.rstrip(), file=sys.stderr)
    print(f"exit:    {code}  ({entry['seconds']}s)")
    print(f"status:  {data['status']}")
    return 0 if code == 0 else 6


def cmd_verify(_args: list[str]) -> int:
    turn_id, data = load_current()
    require(data, {"EXECUTED", "VERIFYING", "VERIFIED"}, "verify")
    # 会话审计：跑过却没进 executions 的命令，打回执行前重做
    bad = unlogged_commands(data)
    if not bad and data.get("violations"):
        bad = list(data["violations"])
    if bad:
        data["status"] = "READ_DONE"
        data.setdefault("failures", []).append(
            {"what": "audit", "commands": bad, "at": now()}
        )
        data["violations"] = []
        save(turn_id, data)
        print(f"打回 READ_DONE：有 {len(bad)} 条命令没记账")
        for cmd in bad:
            print(f"  · {cmd.splitlines()[0][:100]}")
        return 6
    # 审计清了，把上次的 audit 失败记录一并销掉
    data["failures"] = [f for f in data.get("failures", []) if f.get("what") != "audit"]
    # SKILL.md 第 10 节：验收清单有硬性未通过项，不允许进入 VERIFIED
    hard = [n for n, s, _ in collect_checks(turn_id, data) if s == "fail" and n != "测试与验证已执行"]
    if hard:
        data.setdefault("failures", []).append(
            {"what": "verify", "problems": hard, "at": now()}
        )
        data["status"] = "FAILED"
        save(turn_id, data)
        for name in hard:
            print(f"不通过：{name}", file=sys.stderr)
        return 7

    problems = []
    if not data["routes"]:
        problems.append("没有任何路由记录")
    missing = [r["skill"] for r in data["routes"] if r["skill"] not in {x["skill"] for x in data["reads"]}]
    if missing:
        problems.append(f"这些技能没有读取记录：{', '.join(missing)}")
    if not data["executions"]:
        problems.append("没有任何执行记录")
    bad = [e for e in data["executions"] if e["exit"] != 0 and not e.get("allowed_fail")]
    if bad:
        problems.append(f"{len(bad)} 条执行失败（exit≠0）")
    if problems:
        data.setdefault("failures", []).append(
            {"what": "verify", "problems": problems, "at": now()}
        )
        data["status"] = "FAILED"
        save(turn_id, data)
        for p in problems:
            print(f"不通过：{p}", file=sys.stderr)
        return 7
    data["verifications"].append(
        {
            "at": now(),
            "routes": [r["skill"] for r in data["routes"]],
            "executions": len(data["executions"]),
            "result": "ok",
        }
    )
    data["status"] = "VERIFIED"
    save(turn_id, data)
    print(f"验证通过：{len(data['routes'])} 个技能 / {len(data['executions'])} 条执行")
    print("status:  VERIFIED")
    return 0


def cmd_plan(args: list[str]) -> int:
    if not args:
        die("用法：plan <步骤> [<步骤> ...]", 2)
    turn_id, data = load_current()
    require(data, {"ROUTE_PENDING", "ROUTE_DONE", "READ_PENDING", "READ_DONE",
                   "EXECUTING", "EXECUTED"}, "plan")
    cursor = session_total()
    data["plan"] = [{"n": i + 1, "step": s, "at": now()} for i, s in enumerate(args)]
    data["plan_cursor"] = cursor
    save(turn_id, data)
    print(f"路径规划（{len(data['plan'])} 步）")
    for e in data["plan"]:
        print(f"  {e['n']}. {e['step']}")
    return 0


def collect_checks(turn_id: str, data: dict) -> list[tuple[str, str, str]]:
    """逐条对应 SKILL.md 第 10 节的 11 项验收检查。

    ok = 代码能证明；warn = 代码只能旁证，需人工确认；fail = 明确不满足。
    """
    read_skills = {r["skill"] for r in data["reads"]}
    route_skills = [r["skill"] for r in data["routes"]]
    missing = [s for s in route_skills if s not in read_skills]
    bad_runs = [e for e in data["executions"] if e["exit"] != 0 and not e.get("allowed_fail")]
    failures = data.get("failures", [])
    plan = data.get("plan") or []
    reads_ok = bool(data["reads"]) and all(
        r.get("md5") and r.get("bytes") for r in data["reads"]
    )
    cmds_ok = bool(data["executions"]) and all(e.get("cmd") for e in data["executions"])
    return [
        ("已创建独立 turn_id", "ok" if turn_id else "fail", turn_id or "缺失"),
        ("已完整读取 ds-help.md", "ok" if "ds-help" in read_skills else "fail",
         "有 md5 记录" if "ds-help" in read_skills else "无读取记录"),
        ("已依据路由规则判断", "warn" if route_skills else "fail",
         f"记录了 {len(route_skills)} 个技能，判断是否正确需人工复核" if route_skills else "未记录任何路由"),
        ("命中技能均已读原文", "ok" if not missing else "fail",
         ("缺 " + ", ".join(missing)) if missing else "全部已读"),
        ("读取操作均有真实记录", "ok" if reads_ok else "fail", f"{len(data['reads'])} 条带 md5"),
        ("适用的技能要求已执行",
         "ok" if (plan or not data["executions"]) else "fail",
         f"计划 {len(plan)} 步 / 执行 {len(data['executions'])} 条"
         + ("" if (plan or not data["executions"]) else "（干了活却没 plan）")),
        ("实际命令均有结果记录", "ok" if cmds_ok else "fail",
         f"{len(data['executions'])} 条含 cmd 与退出码"),
        ("测试与验证已执行", "warn" if data["verifications"] else "fail",
         "有 verify 记录，具体测什么需人工复核" if data["verifications"] else "未 verify"),
        ("无未解决阻塞或失败", "ok" if (not failures and not bad_runs) else "fail",
         "无" if (not failures and not bad_runs) else f"failures {len(failures)} / 失败命令 {len(bad_runs)}"),
        ("无越界命令", "ok" if not data.get("violations") else "fail",
         "无" if not data.get("violations") else f"{len(data['violations'])} 条绕过 workflow.py"),
        ("状态文件与实际一致", "warn", "需人工核对"),
        ("最终结果符合任务要求", "warn", "需人工判定"),
    ]


def cmd_check(_args: list[str]) -> int:
    turn_id, data = load_current()
    items = collect_checks(turn_id, data)
    print("验收清单")
    for i, (name, state, detail) in enumerate(items, 1):
        mark = {"ok": "x", "warn": "!", "fail": " "}[state]
        print(f"  [{mark}] {i:2d}. {name:<14} {detail}")
    hard = [n for n, s, _ in items if s == "fail"]
    soft = [n for n, s, _ in items if s == "warn"]
    if hard:
        print(f"未通过：{', '.join(hard)}")
        return 8
    print("全部通过" + (f"（{len(soft)} 项待人工确认：{', '.join(soft)}）" if soft else ""))
    return 0


def cmd_stop(_args: list[str]) -> int:
    turn_id, data = load_current()
    if data["status"] in TERMINAL_BAD:
        die(f"本轮状态 {data['status']}，不能标记完成", 4)
    if data["status"] != "VERIFIED":
        die(f"当前 {data['status']}，必须先 verify 通过才能 stop", 4)
    if not data["verifications"]:
        die("没有验证记录，不能 stop", 4)
    hard = [n for n, s, _ in collect_checks(turn_id, data) if s == "fail"]
    if hard:
        die(f"验收清单未通过：{', '.join(hard)}", 4)
    data["completion"] = {
        "at": now(),
        "routes": [r["skill"] for r in data["routes"]],
        "reads": [r["skill"] for r in data["reads"]],
        "executions": len(data["executions"]),
    }
    data["status"] = "COMPLETED"
    save(turn_id, data)
    print(f"完成：{turn_id}")
    print(f"status:  COMPLETED")
    return 0


def cmd_status(_args: list[str]) -> int:
    if not ptr_for(current_session_id()).is_file():
        print("本轮还没有 start")
        return 3
    turn_id, data = load_current()
    print(f"turn_id: {turn_id}")
    print(f"status:  {data['status']}")
    print(f"routes:  {', '.join(r['skill'] for r in data['routes']) or '（空）'}")
    print(f"reads:   {', '.join(r['skill'] for r in data['reads']) or '（空）'}")
    print(f"runs:    {len(data['executions'])} 条")
    for e in data["executions"]:
        print(f"         [{e['exit']}] {e['cmd']}")
    return 0


def cmd_report(_args: list[str]) -> int:
    turn_id, data = load_current()
    clock = lambda s: (s or "")[11:19]  # noqa: E731
    print(f"turn {turn_id}   {data['status']}")
    rows = []
    for r in data["routes"]:
        rows.append((r["at"], "route", r["skill"], r.get("source", "")))
    for r in data["reads"]:
        rows.append((r["at"], "read", r["skill"],
                     f"{r.get('lines', '?')} 行  md5 {str(r.get('md5', ''))[:8]} · {r.get('source', '')}"))
    for p in data.get("plan") or []:
        rows.append((p["at"], "plan", f"{p['n']}. {p['step']}", ""))
    for e in data["executions"]:
        rows.append((e["at"], "run", e["cmd"].splitlines()[0][:46],
                     f"exit {e['exit']} · {e['seconds']}s"))
    rows.sort(key=lambda x: x[0])
    for at, act, obj, detail in rows:
        print(f"  {clock(at)}  {act:<5} {obj:<30} {detail}")
    if not rows:
        print("  （还没有记录）")
    for v in data.get("violations") or []:
        print(f"  ! 越界命令：{v[:80]}")
    for f in data.get("failures") or []:
        print(f"  ! 失败：{f.get('what')} {str(f.get('problems') or f.get('commands') or '')[:70]}")
    return 0


COMMANDS = {
    "start": cmd_start,
    "route": cmd_route,
    "read": cmd_read,
    "run": cmd_run,
    "verify": cmd_verify,
    "stop": cmd_stop,
    "plan": cmd_plan,
    "check": cmd_check,
    "status": cmd_status,
    "abandon": cmd_abandon,
    "report": cmd_report,
}


def guard() -> None:
    """每次调用都先查一次：上次检查到现在，有没有绕过 workflow.py 的命令。"""
    try:
        turn_id, data = load_current()
    except SystemExit:
        return
    base = data.get("checked_total", data.get("baseline_total"))
    total = session_total()
    if total is None:
        return
    if base is not None and total > base:
        bad = []
        for cmd, title in session_commands(base, total):
            wf, others = parse_segments(cmd)
            bad.extend(others)
            if not wf and not others:
                bad.append(cmd.splitlines()[0][:100])
            if wf and title:
                bad.extend(check_titles(cmd, title, data))
        bad.extend(first_call_problem(data))
        if bad:
            data.setdefault("violations", []).extend(bad)
            print("越界命令（没经过 workflow.py）：")
            for c in bad:
                print(f"  · {c[:90]}")
    data["checked_total"] = total
    save(turn_id, data)


def audit_tail() -> None:
    """每次调用结束时立刻复核一次：这一轮有没有绕过 workflow.py 的东西。"""
    try:
        turn_id, data = load_current()
    except SystemExit:
        return
    bad = unlogged_commands(data) + first_call_problem(data)
    data["violations"] = bad  # 以全量重扫结果为准，旧的误报不再累积
    if bad:
        data.setdefault("violations", [])
        for b in bad:
            if b not in data["violations"]:
                data["violations"].append(b)
        save(turn_id, data)
        print(f"审计：{len(data['violations'])} 条越界 → 先修，再继续")
        for b in data["violations"][:5]:
            print(f"  · {b[:90]}")
    else:
        print(f"审计：通过（{data['status']}，路由 {len(data['routes'])} / 读取 {len(data['reads'])} / 执行 {len(data['executions'])}）")


NATIVE_TOOLS = {
    "file_write", "file_edit", "file_read", "browser_use",
    "subagent_task", "user_ask", "read_image", "memory_write", "memory_get",
}


def previous_tool_call(data: dict) -> dict | None:
    """本轮里这一次调用之前的最后一个工具调用。"""
    base = data.get("baseline_total")
    total = session_total()
    if base is None or total is None:
        return None
    calls = session_calls(base, total)
    return calls[-1] if calls else None


def auto_verify() -> None:
    """上一枪是原生工具（file_write 等）就顺手做一次 verify，否则放行。"""
    try:
        turn_id, data = load_current()
    except SystemExit:
        return
    prev = previous_tool_call(data)
    if not prev or prev["name"] not in NATIVE_TOOLS:
        return
    bad = unlogged_commands(data) + first_call_problem(data)
    if prev["name"] in ("file_write", "file_edit"):
        ready = {"READ_DONE", "EXECUTING", "EXECUTED", "VERIFIED"}
        if data["status"] not in ready:
            bad.append(f"改文件前没读完命中技能（状态 {data['status']}）")
        if not data.get("plan"):
            bad.append("改文件前没写路径规划")
    what = prev["title"] or prev["cmd"][:40] or prev["name"]
    if bad:
        data["violations"] = bad
        save(turn_id, data)
        print(f"自动 verify（上一枪 {prev['name']}「{what}」）：{len(bad)} 条问题")
        for b in bad[:5]:
            print(f"  · {b[:90]}")
        return
    data["auto_verifies"] = (data.get("auto_verifies") or 0) + 1
    save(turn_id, data)
    print(f"自动 verify（上一枪 {prev['name']}「{what}」）：通过")


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    name = sys.argv[1]
    fn = COMMANDS.get(name)
    if not fn:
        die(f"未知命令：{name}（可用：{' '.join(COMMANDS)}）", 2)
    if name != "start":
        guard()
        auto_verify()
        try:
            _tid, _data = load_current()
        except SystemExit:
            raise
        anchor = _data.get("anchor_msg_id")
        latest = latest_user_msg_id()
        if anchor and latest and anchor != latest:
            print("⚠ 工作流中途停止：用户输入了新消息，请开新一轮重新规划！", file=sys.stderr)
            print("   执行命令：python scripts/workflow.py start", file=sys.stderr)
            print(f"   上次消息 id：{anchor}", file=sys.stderr)
            print(f"   当前消息 id：{latest}", file=sys.stderr)
            return 10
    rc = fn(sys.argv[2:])
    audit_tail()
    return rc


if __name__ == "__main__":
    sys.exit(main())
