#!/usr/bin/env python3
"""敏感信息扫描与脱敏。

报告只输出打码后的片段，不打印明文。
打码规则：默认只留首尾各一个字；密码类（密码赋值、Bearer 令牌、私钥）全星号。
"""

import re

MASK_HEAD = 1
MASK_TAIL = 1


def mask(value, full=False):
    """默认留首尾各一个字；full=True 时全部替换成 *。"""
    if full or len(value) <= MASK_HEAD + MASK_TAIL:
        return "*" * max(1, len(value))
    return value[:MASK_HEAD] + "*" * (len(value) - MASK_HEAD - MASK_TAIL) + value[-MASK_TAIL:]


# (名称, 正则, 严重度, 是否全遮)
PATTERNS = [
    ("OpenAI/兼容 key", r"\bsk-[A-Za-z0-9_-]{16,}", "high", True),
    ("GitHub token", r"\bgh[pousr]_[A-Za-z0-9]{20,}", "high", True),
    ("GitHub fine-grained token", r"\bgithub_pat_[A-Za-z0-9_]{20,}", "high", True),
    ("AWS access key", r"\bAKIA[0-9A-Z]{16}\b", "high", True),
    ("Slack token", r"\bxox[abprs]-[A-Za-z0-9-]{10,}", "high", True),
    ("私钥块", r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "high", True),
    ("JWT", r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}", "high", True),
    ("Bearer 令牌", r"[Bb]earer\s+([A-Za-z0-9._~+/=-]{20,})", "high", True),
    ("长十六进制串", r"(?<![0-9a-fA-F])[0-9a-fA-F]{32,}(?![0-9a-fA-F])", "medium", False),
    ("手机号", r"(?<!\d)1[3-9]\d{9}(?!\d)", "high", False),
    ("邮箱", r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "medium", False),
    ("IPv4 地址", r"(?<![\d.])(?:(?!127\.|0\.0\.0\.0)[0-9]{1,3}\.){3}[0-9]{1,3}(?![\d.])", "low", False),
    ("密码赋值", r"(?i)(?:password|passwd|pwd|密码|口令)\s*[:=]\s*([^\s\"',，。]{4,})", "high", True),
    ("账号名", r"(?:账号|account)\s*[:：]?\s*[`'\"]?([A-Za-z][A-Za-z0-9_.-]{2,})", "low", False),
]

COMPILED = [(n, re.compile(p), s, f) for n, p, s, f in PATTERNS]

# 只对这些严重度做脱敏；low 只报告不改写（公网 DNS 之类不是隐私）
FIX_SEVERITY = ("high", "medium")


def scan_text(text):
    """返回 [(行号, 类型, 严重度, 打码片段)]（含 low，供报告用）。"""
    hits = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for name, rx, sev, full in COMPILED:
            for m in rx.finditer(line):
                raw = m.group(1) if m.lastindex and m.group(m.lastindex) else m.group(0)
                hits.append((lineno, name, sev, mask(raw, full)))
    return hits


def redact_text(text):
    """把 high/medium 命中项替换成打码版，返回 (新文本, 改动行数)。"""
    def sub_for(full):
        def sub(m):
            if m.lastindex and m.group(m.lastindex):
                whole = m.group(0)
                raw = m.group(m.lastindex)
                return whole.replace(raw, mask(raw, full))
            return mask(m.group(0), full)
        return sub

    new = text
    for _name, rx, sev, full in COMPILED:
        if sev not in FIX_SEVERITY:
            continue
        new = rx.sub(sub_for(full), new)
    changed = sum(1 for a, b in zip(text.splitlines(), new.splitlines()) if a != b)
    return new, changed


def report(hits):
    """把命中清单转成给人看的行，不含明文。"""
    return ["  第 %d 行 · %s · %s · %s" % (n, name, sev, masked)
            for n, name, sev, masked in hits]
