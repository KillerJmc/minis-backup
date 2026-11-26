#!/usr/bin/env python3
"""账号凭证的统一读取与解析（四个平台共用）。

账号不在配置文件里存，只从环境变量取，格式是「账号<分隔符>密码」：

    QUOTA_MINEKUAI_CRED    只填手机号
    QUOTA_MODELSCOPE_CRED  只填手机号
    QUOTA_QINIU_CRED       账号<分隔符>密码
    QUOTA_MIAOTOKEN_CRED   账号<分隔符>密码

分隔符认英文分号、中文分号、空格，按第一个出现的切开；
没有分隔符时整段视为账号（短信验证码类平台）。

只按第一个分隔符切，因此密码里再出现分号不会被截断。

隐私：本模块负责报错文案，任何返回值都不含明文密码之外的推断；
调用方不应把 password 打印或写盘。
"""
from __future__ import annotations

import os
import re

# 环境变量名与平台标识的映射
VAR_MAP = {
    "minekuai": "QUOTA_MINEKUAI_CRED",
    "modelscope": "QUOTA_MODELSCOPE_CRED",
    "qiniu": "QUOTA_QINIU_CRED",
    "miaotoken": "QUOTA_MIAOTOKEN_CRED",
}

DELIMS = (";", "；", " ")


class CredentialError(RuntimeError):
    """凭证缺失或格式不对。"""


def var_name(platform: str) -> str:
    return VAR_MAP.get(platform, f"QUOTA_{platform.upper()}_CRED")


# 无分隔符时用来定位账号结尾的形态。
# 邮箱用常见顶级域白名单 + 后向断言，避免把密码开头的字母吞进域名：
# 「a@b.comXyz」不会被误判为邮箱「a@b.comXyz」。
_TLDS = ("com", "cn", "net", "org", "io", "cc", "co", "me", "tv", "xyz",
         "top", "info", "dev", "app", "ai", "edu", "gov", "site", "online",
         "store", "tech", "link", "club", "vip", "pro", "work", "shop")
EMAIL_RE = re.compile(
    r"[^@\s]+@[^@\s]+?\.(?:" + "|".join(_TLDS) + r")(?![A-Za-z0-9])",
    re.IGNORECASE)
PHONE_RE = re.compile(r"1\d{10}")


def parse(raw: str) -> tuple[str, str]:
    """把「账号<分隔符>密码」拆成 (账号, 密码)。

    分隔符认英文分号、中文分号、空格，按第一个出现的切开。
    没有分隔符时按账号形态猜边界：先试邮箱，再试 11 位手机号；
    都对不上则整段视为账号（短信验证码类平台）。
    猜出的账号必须后面还有字符，否则视为只有账号。
    """
    raw = (raw or "").strip()
    if not raw:
        return "", ""

    pos = -1
    for d in DELIMS:
        i = raw.find(d)
        if i != -1 and (pos == -1 or i < pos):
            pos = i
    if pos != -1:
        return raw[:pos].strip(), raw[pos + 1:].strip()

    for pat in (EMAIL_RE, PHONE_RE):
        m = pat.match(raw)
        if m and m.end() < len(raw):
            return m.group(0).strip(), raw[m.end():].strip()

    return raw, ""


def load(platform: str, need_password: bool = False) -> tuple[str, str]:
    """读环境变量并解析。缺账号或缺密码时抛 CredentialError。

    need_password=True 用于密码登录类平台；短信验证码类平台只校验账号。
    """
    name = var_name(platform)
    raw = os.environ.get(name, "")
    if not raw.strip():
        raise CredentialError(
            f"缺少环境变量 {name}。请到 设置 → 环境变量 添加，"
            f"格式：{'账号；密码' if need_password else '手机号'}"
        )
    account, password = parse(raw)
    if not account:
        raise CredentialError(f"{name} 里没有解析出账号，请检查格式")
    if need_password and not password:
        raise CredentialError(
            f"{name} 缺少密码段。格式应为「账号；密码」，"
            f"分隔符可用中英文分号或空格"
        )
    return account, password


def masked_account(platform: str) -> str:
    """取打码后的账号用于显示；读不到时返回空串。"""
    name = var_name(platform)
    raw = os.environ.get(name, "")
    if not raw.strip():
        return ""
    account, _ = parse(raw)
    if not account:
        return ""
    if "@" in account:
        local, _, domain = account.partition("@")
        head = local[0] if local else ""
        return f"{head}****@{domain}"
    if len(account) >= 7 and account.isdigit():
        return f"{account[0]}{'*' * (len(account) - 2)}{account[-1]}"
    if len(account) <= 2:
        return "*" * len(account)
    return f"{account[0]}{'*' * (len(account) - 2)}{account[-1]}"