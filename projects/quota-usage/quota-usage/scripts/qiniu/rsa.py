#!/usr/bin/env python3
"""纯 Python 的 RSA 公钥加密（PKCS#1 v1.5），用于七牛 SSO 登录。

不依赖 cryptography / pycryptodome：只需 base64 与 os.urandom。
只做「公钥加密」，不涉及私钥与签名。
"""
from __future__ import annotations

import base64
import os


# ---------- 最小 ASN.1 解析 ----------

def _read_len(buf: bytes, i: int) -> tuple[int, int]:
    """读 DER 长度，返回 (长度, 新偏移)。"""
    b = buf[i]
    i += 1
    if b < 0x80:
        return b, i
    n = b & 0x7F
    return int.from_bytes(buf[i:i + n], "big"), i + n


def _read_tlv(buf: bytes, i: int) -> tuple[int, bytes, int]:
    """读一个 TLV，返回 (tag, value, 新偏移)。"""
    tag = buf[i]
    i += 1
    length, i = _read_len(buf, i)
    return tag, buf[i:i + length], i + length


def _parse_rsa_public_key(pem: str) -> tuple[int, int]:
    """从 PEM 里取出 (n, e)，兼容 SPKI 与裸 PKCS#1 两种包裹。"""
    body = "".join(l for l in pem.splitlines() if not l.startswith("-----")).strip()
    der = base64.b64decode(body)
    tag, seq, _ = _read_tlv(der, 0)
    if tag != 0x30:
        raise ValueError("公钥不是 DER SEQUENCE")

    # 先按 SPKI 试：SEQUENCE { AlgorithmIdentifier, BIT STRING }
    tag1, val1, off1 = _read_tlv(seq, 0)
    if tag1 == 0x30:
        tag2, val2, _ = _read_tlv(seq, off1)
        if tag2 == 0x03:                      # BIT STRING，内容前有一字节 padding 标记
            inner = val2[1:]
            tag3, seq2, _ = _read_tlv(inner, 0)
            if tag3 == 0x30:
                seq = seq2
    # 现在 seq 是 RSAPublicKey { INTEGER n, INTEGER e }
    tag, n_bytes, off = _read_tlv(seq, 0)
    if tag != 0x02:
        raise ValueError("缺少 modulus")
    tag, e_bytes, _ = _read_tlv(seq, off)
    if tag != 0x02:
        raise ValueError("缺少 exponent")
    return int.from_bytes(n_bytes, "big"), int.from_bytes(e_bytes, "big")


# ---------- PKCS#1 v1.5 加密 ----------

def encrypt_pkcs1v15(pem: str, message: str) -> str:
    """用公钥加密字符串，返回 base64 密文（与浏览器端 jsencrypt 一致）。"""
    n, e = _parse_rsa_public_key(pem)
    k = (n.bit_length() + 7) // 8          # 模长字节数，2048 位 = 256
    msg = message.encode("utf-8")
    if len(msg) > k - 11:
        raise ValueError("明文过长，超过 PKCS#1 v1.5 容量")

    ps_len = k - len(msg) - 3
    ps = bytearray()
    while len(ps) < ps_len:                # 填充串必须非零
        ps.extend(b for b in os.urandom(ps_len - len(ps)) if b != 0)
    em = b"\x00\x02" + bytes(ps[:ps_len]) + b"\x00" + msg
    c = pow(int.from_bytes(em, "big"), e, n)
    return base64.b64encode(c.to_bytes(k, "big")).decode("ascii")