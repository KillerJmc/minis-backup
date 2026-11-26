# 七牛登录态失效 → 重新登录

`quota.py` / `checkin.py` 退出码 `3`（`AUTH_EXPIRED`）时执行本流程。

七牛额度接口只需要**一个 Cookie：`PORTAL_SESSION`**（124 字符）。
SSID / PORTAL_UID 都**不是必需的**（实测去掉后接口照常返回）。

---

## 方式一：纯 HTTP 登录（助手全自动，用户零操作）

脚本已实现完整链路，**不需要打开浏览器**：

```
1) GET  web-api.qiniu.com/api/proxy/uc-biz/passport/public-key   取 RSA 公钥
   （必须带 Referer/Origin: https://sso.qiniu.com，否则 403）
2) 邮箱账号 → sign_in_type=1，username 用原文
   手机账号 → 先 GET sso.qiniu.com/user-ids?phone_number=<号> 取 user_id，
              sign_in_type=2，username 用该 user_id
3) RSA/PKCS#1 v1.5 加密密码（纯 Python，scripts/qiniu/rsa.py）
4) POST sso.qiniu.com/signin?client_id=&redirect_url=  取 PORTAL_SESSION
```

**已知门槛**：账号若存在未完成的「合规验证」，登录接口返回
`HTTP 400 require compliance verification`（前端会跳 `/compliance-verification`）。
这一步涉及身份核验，只能账号本人在浏览器里完成一次；完成后本流程即可全自动。

## 方式一（旧）：浏览器账号密码

账号与密码已存在环境变量 `QUOTA_QINIU_CRED`（格式 `账号；密码`），
助手用 `credentials.load("qiniu", need_password=True)` 取出后直接填表，
**不要**让用户输入、不要打印密码。

```
1) 浏览器打开 https://sso.qiniu.com/
   - 移动 UA + 390x844 即可，桌面 UA 也行
   - 页面只有「账号密码登录」和「微信登录」两个 tab

2) 填表：
   #email    → 手机号（如 13800000000）
   #password → 密码
   - 勾选协议（如有）
   - 图形验证码 #captcha 平时是 hidden 的，出现时才要认

3) 提交：用 MouseEvent 派发 mousedown/mouseup/click，直接 .click() 有时不触发
   const btn = [...document.querySelectorAll('button')].filter(e=>e.innerText.trim()==='登录')[0];
   const r = btn.getBoundingClientRect();
   const o = {bubbles:true, cancelable:true, clientX:r.left+r.width/2, clientY:r.top+r.height/2, view:window};
   ['mousedown','mouseup','click'].forEach(t=>btn.dispatchEvent(new MouseEvent(t,o)));

4) 成功标志：跳到 https://portal.qiniu.com/home（标题「七牛云控制台 - 产品主页」）

5) 落盘：
   get_cookies keywords=PORTAL_SESSION  → env 文件
   python3 .../login.py --from-env <env 文件>

6) 验证：
   python3 .../login.py --check
   python3 .../quota.py
```

---

## 方式二：已有 cookie 时直接落盘

助手从浏览器 cookie 取到 `PORTAL_SESSION` 后：

```sh
python3 .../login.py --value <PORTAL_SESSION>
```

`login.py` 会先打额度接口校验，**无效不覆盖**。
**不要让用户提供这个值**——cookie 技术性强，属助手职责。

---

## 方式三：微信登录（实测不可用，别浪费时间）

七牛的「微信登录」**不是扫码**，而是跳微信小程序：

```
POST web-api.qiniu.com/api/proxy/uc-biz/wx/mini-program/url-link
  → {"url_link": "https://wxmpurl.cn/ozBtIZrs32r"}
```

**这个短链是固定的**，不随会话变化，而且生成接口**不需要登录**：

```sh
curl -s "https://web-api.qiniu.com/api/proxy/uc-biz/wx/mini-program/url-link?path=%2Fpages%2Fcommon%2Fweb-view%2Findex&query=url%3D" \
  -H 'accept: application/json' -H 'origin: https://sso.qiniu.com' -H 'referer: https://sso.qiniu.com/'
```

**为什么不可用（2026-11-18 / 11-21 两次实测）**：

| 环节 | 结果 |
|---|---|
| 在微信里打开短链 | 显示「请在手机打开网页链接」 |
| 点右上角 ⋯ → 用默认浏览器打开 | 能唤起微信 |
| 小程序被唤起 | **白屏**（拿不到 scene/code 参数） |
| 拼回调参数重新生成短链 | 仍白屏 |

小程序必须从微信内部正常进入才能拿到完整参数，外链唤起一律白屏。
**不要再尝试这条路。**

---

## 踩坑记录

| 现象 | 原因 / 解决 |
|---|---|
| `sso.qiniu.com` 打开卡死、白屏 30s+ | 页面引用的第三方脚本（Clarity / ByteDance / GA）拖住渲染。换个新标签页再开，或直接访问 `portal.qiniu.com/login` |
| 清理浏览器数据后 cookie 仍显示登录 | `sso.qiniu.com` 的会话是 HttpOnly，`set_cookies` 覆盖不掉，只能真点「退出登录」 |
| 生效前 `get` 读回 `None` | `add groups` 传的 `fallbackStrategy` 不会写入，要单独 `set` 一次 |
| 活动额度接口 `used` 恒为 0 | 服务端没统计。真实消耗走 `v3/stat/new`，单位是 **K token**，要 ×1000 |

---

## 当前账号信息

- 账号：由环境变量 `QUOTA_QINIU_CRED` 提供，本文件不记录手机号与 uid
- 配置：`/var/minis/shared/quota/qiniu.json`（0600），只存 `portal_session` / `campaign_id` / `user_model` / `saved_at`
- 有效期：以七牛会话为准，实测可用多天；失效时重跑本流程