#!/usr/bin/env python3
"""七牛登录的浏览器操作助手。

账号密码从环境变量 QUOTA_QINIU_CRED 读，注入页面后点击登录，
凭证不打印、不出现在助手上下文。

用法:
  qiniu_login_helper.py fill       填账号密码
  qiniu_login.py state            查状态（是否已登录 / 是否要合规验证）
"""
import json
import os
import subprocess
import sys

TAB = os.environ.get("QN_LOGIN_TAB", "2")

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
    if not out.get("ok", True):
        return f"ERR:{json.dumps(out.get('error'), ensure_ascii=False)[:200]}"
    return str((out.get("data") or {}).get("text") or "")


def get_cred() -> tuple[str, str]:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, root)
    import credentials  # noqa: E402

    try:
        return credentials.load("qiniu", need_password=True)
    except credentials.CredentialError as exc:
        print(f"缺少凭证：{exc}", file=sys.stderr)
        sys.exit(4)


def cmd_fill() -> int:
    account, password = get_cred()
    js = JS_SET + JS_CLICK + """
const acc = %s, pwd = %s;
const e = document.querySelector('#email');
const p = document.querySelector('#password');
if (!e || !p) return 'no-form';
set(e, acc);
set(p, pwd);
const btn = [...document.querySelectorAll('button')]
  .filter(x => x.innerText && x.innerText.trim() === '登录')[0];
if (!btn) return 'no-btn';
fire(btn);
return JSON.stringify({filled: true, accLen: acc.length});
""" % (json.dumps(account), json.dumps(password))
    print(run_js(js))
    return 0


def cmd_state() -> int:
    js = """return JSON.stringify({
  url: location.href,
  title: document.title,
  bodyHint: (document.body.innerText || '').slice(0, 160),
  hasLoginForm: !!document.querySelector('#email')
});"""
    print(run_js(js))
    return 0


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "state"
    if cmd == "fill":
        return cmd_fill()
    return cmd_state()


if __name__ == "__main__":
    sys.exit(main())