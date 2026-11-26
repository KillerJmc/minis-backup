#!/usr/bin/env python3
"""魔搭登录的浏览器操作助手。

让手机号与验证码不经过助手的上下文：手机号从环境变量读，
验证码从命令行读，两者都只写进页面，不打印。

依赖环境里有 `minis-browser-use` 命令，且目标 tab 已导航到
passport.modelscope.cn 的同源登录页（见 references/modelscope-relogin.md）。

用法:
  login_helper.py switch-sms              切到短信登录
  login_helper.py fill-and-send           填手机号 + 勾协议 + 发码
  login_helper.py submit-code 123456      填验证码并提交
  login_helper.py state                   报告当前状态（不含凭证）

环境变量:
  MS_LOGIN_TAB    浏览器 tab id，默认 1

退出码:
  0 成功
  2 页面元素找不到（多半是导航错了或不是同源页）
  4 缺账号变量
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

TAB = os.environ.get("MS_LOGIN_TAB", "1")

JS_SET = """
const set = (el, v) => {
  const s = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  s.call(el, v);
  el.dispatchEvent(new Event('input',  {bubbles: true}));
  el.dispatchEvent(new Event('change', {bubbles: true}));
};
"""

JS_CLICK = """
const fire = (el) => {
  const r = el.getBoundingClientRect();
  const o = {bubbles: true, cancelable: true,
             clientX: r.left + r.width / 2, clientY: r.top + r.height / 2, view: window};
  ['mousedown', 'mouseup', 'click'].forEach(t => el.dispatchEvent(new MouseEvent(t, o)));
};
"""


def run_js(script: str) -> str:
    proc = subprocess.run(
        ["minis-browser-use", "execute_js", "--tab_id", TAB, "--json",
         json.dumps({"action": "execute_js", "script": script}, ensure_ascii=False)],
        capture_output=True, text=True, timeout=120,
    )
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return f"RAW:{proc.stdout[:200]}"
    data = out.get("data") or {}
    if not out.get("ok", True):
        return f"ERR:{json.dumps(out.get('error'), ensure_ascii=False)[:200]}"
    return str(data.get("text") or "").replace("\n  tab_id: " + TAB, "").strip()


def get_phone() -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, root)
    import credentials  # noqa: E402

    try:
        account, _ = credentials.load("modelscope")
    except credentials.CredentialError as exc:
        print(f"缺少凭证：{exc}", file=sys.stderr)
        sys.exit(4)
    return account


def cmd_switch_sms() -> int:
    js = """const tabs = [...document.querySelectorAll('div,span,a,button')]
      .filter(e => e.innerText && e.innerText.trim() === '短信登录');
if (!tabs.length) return 'no-sms-tab';
tabs[tabs.length - 1].click();
return 'switched';"""
    print(run_js(js))
    return 0


def cmd_fill_and_send() -> int:
    phone = get_phone()
    js = JS_SET + """
const phone = %s;
const el = document.querySelector('#fm-sms-login-id');
if (!el) return 'no-phone-input';
set(el, phone);

// 协议必须点可见的 input[type=checkbox]，点外层 div 无效
const cb = [...document.querySelectorAll('input[type=checkbox]')]
  .find(i => i.offsetParent !== null);
if (cb && !cb.checked) cb.click();

// 发码按钮连点两次：第一次可能因协议尚未生效而失败
const btn = [...document.querySelectorAll('button,div,span,a')]
  .filter(e => e.innerText && e.innerText.trim() === '获取验证码');
if (!btn.length) return JSON.stringify({filled: true, sent: false});
const target = btn[btn.length - 1];
target.click();
return JSON.stringify({filled: true, sent: true, codeLen: (phone || '').length});
""" % json.dumps(phone)
    print(run_js(js))
    return 0


def cmd_submit_code(code: str) -> int:
    code = code.strip()
    if not (code.isdigit() and len(code) == 6):
        print("验证码应为 6 位数字", file=sys.stderr)
        return 2
    js = JS_SET + JS_CLICK + """
const code = %s;
const el = document.querySelector('#fm-smscode');
if (!el) return 'no-code-input';
set(el, code);
const btn = [...document.querySelectorAll('button')]
  .filter(e => e.innerText && e.innerText.trim() === '登录').pop();
if (!btn) return 'no-login-btn';
fire(btn);
return 'submitted';
""" % json.dumps(code)
    print(run_js(js))
    return 0


def cmd_state() -> int:
    js = """const phone = document.querySelector('#fm-sms-login-id');
const code = document.querySelector('#fm-smscode');
const texts = [...new Set([...document.querySelectorAll('button,div,span,a')]
  .map(e => e.innerText && e.innerText.trim())
  .filter(t => t && /秒后重发|验证码|登录中/.test(t)))].slice(0, 4);
const msg = [...document.querySelectorAll('[class*=error],[class*=toast],[class*=tip]')]
  .map(e => e.innerText.trim()).filter(Boolean).slice(0, 3);
return JSON.stringify({
  phoneFilled: phone ? phone.value.length > 0 : false,
  codeFilled: code ? code.value.length : 0,
  texts, msg, title: document.title});
"""
    print(run_js(js))
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    if cmd == "switch-sms":
        return cmd_switch_sms()
    if cmd == "fill-and-send":
        return cmd_fill_and_send()
    if cmd == "submit-code":
        if len(sys.argv) < 3:
            print("需要 6 位验证码", file=sys.stderr)
            return 2
        return cmd_submit_code(sys.argv[2])
    if cmd == "state":
        return cmd_state()
    print(f"未知子命令 {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())