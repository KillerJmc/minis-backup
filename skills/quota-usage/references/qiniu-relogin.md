# 七牛登录态失效 → 重新登录

`quota.py` / `checkin.py` 退出码 `3`（`AUTH_EXPIRED`）时执行本流程。

七牛额度接口只需要**一个 Cookie：`PORTAL_SESSION`**（124 字符）。
SSID / PORTAL_UID 都**不是必需的**（实测去掉后接口照常返回）。

---

## 方式一：账号密码（推荐，最省事）

实测 2026-11-21：一次通过，**没有弹图形验证码**。

```
1) 浏览器打开 https://sso.qiniu.com/
   - 移动 UA + 390x844 即可，桌面 UA 也行
   - 页面只有「账号密码登录」和「微信登录」两个 tab

2) 填表：
   #email    → 手机号（如 13681560565）
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
   python3 .../login.py --from-env <env 文件> --phone <手机号>

6) 验证：
   python3 .../login.py --check
   python3 .../quota.py
```

---

## 方式二：直接给值（最快）

用户能拿到 `PORTAL_SESSION` 时一步到位：

```sh
python3 .../login.py --value <PORTAL_SESSION>
```

`login.py` 会先打额度接口校验，**无效不覆盖**。

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

- 账号：手机号 13681560565，主账号 uid 1383813297
- 配置：`/var/minis/shared/qiniu-quota/config.json`（0600）
- 有效期：以七牛会话为准，实测可用多天；失效时重跑本流程