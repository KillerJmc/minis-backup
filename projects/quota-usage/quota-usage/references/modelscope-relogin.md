# 魔搭登录（助手全自动）

`quota.py` 退出码 `3`（`AUTH_EXPIRED`）时执行。

**用户零操作**：全程由助手完成，用户唯一可能要提供的是 6 位短信验证码
（仅在站点要求时），绝不要求用户开终端、导出 cookie 或提供任何凭证。

账号：环境变量 `QUOTA_MODELSCOPE_CRED`（只填手机号）。
`credentials.load("modelscope")` 取号，**不要打印、不要截图露出**。

---

## 为什么不能纯 HTTP

短信接口 `/newlogin/sms/send.do` 由阿里 baxia 风控保护，放行条件是
「JS 现场签名 + `_uab_collina` 与真实 TLS 指纹一致」。python / curl /
curl_cffi / jsdom 复算全部被 `RGV587` 拦截（已实测穷尽）。
**必须用真浏览器**，但除浏览器操作外全部自动化。

---

## 0. 前置

- 浏览器必须是**移动形态**：`set_user_agent mobile_safari` + `set_viewport 390x844`
- 桌面 UA 会把表单塞进 passport 的跨域 iframe，主页面 JS 操作不到

## 1. 取得同源登录页

```js
// 在 https://modelscope.cn/login 上执行
document.querySelector('iframe').src
// → https://passport.modelscope.cn/mini_login.htm?...
```

**直接 navigate 到这个地址，并把 `isMobile=false` 改成 `isMobile=true`**，
页面就变成同源、可直接操作的表单。

导航后 `document.title` 应为「登录」。

## 2. 切到短信登录并填号

页面默认是**密码登录**，要先点「短信登录」：

```js
const tabs = [...document.querySelectorAll('div,span,a,button')]
  .filter(e => e.innerText && e.innerText.trim() === '短信登录');
tabs[tabs.length - 1].click();
```

切换后出现两个输入框：

| 元素 | 用途 |
|---|---|
| `#fm-sms-login-id` | 手机号 |
| `#fm-smscode` | 验证码 |
| `input[type=checkbox]`（可见的那个） | 协议勾选 |

## 3. 填手机号并发码

**手机号不要经过助手上下文**——用 shell 侧脚本运行时从环境变量读取后注入：

```sh
python3 scripts/modelscope/login_helper.py fill-and-send
```

该脚本内部做的事（等价 JS）：

```js
const set = (el, v) => {
  const s = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  s.call(el, v);
  el.dispatchEvent(new Event('input',  {bubbles: true}));
  el.dispatchEvent(new Event('change', {bubbles: true}));
};
set(document.querySelector('#fm-sms-login-id'), PHONE);

// 协议：必须点可见的 input[type=checkbox]，点外层 div 无效
const cb = [...document.querySelectorAll('input[type=checkbox]')]
  .find(i => i.offsetParent !== null);
if (cb && !cb.checked) cb.click();

// 发码按钮要点两次：第一次可能因协议未生效而失败
const btn = [...document.querySelectorAll('button,div,span,a')]
  .filter(e => e.innerText && e.innerText.trim() === '获取验证码');
btn[btn.length - 1].click();
```

**成功标志**（三处同时出现）：
- 按钮文案变「N秒后重发」
- 出现「短信验证码已发送，可能会有延后，请耐心等待」
- 表单仍停在短信登录页

**「请阅读并同意协议」这个红条会残留**，即使协议已勾选、短信已发出。
**以「N秒后重发」为准，不要被这个红条误导。**

**60 秒冷却**：重复点击会失败，等倒计时结束再点。
若返回 punish 页 / `RGV587`：立即停手（继续试会升级风控），30 分钟后再来。

## 4. 取验证码并提交

向用户要 6 位码（`user_ask` 或直接问），然后：

```sh
python3 scripts/modelscope/login_helper.py submit-code <6位码>
```

等价 JS：

```js
set(document.querySelector('#fm-smscode'), CODE);
const btn = [...document.querySelectorAll('button')]
  .filter(e => e.innerText.trim() === '登录').pop();
const r = btn.getBoundingClientRect();
const o = {bubbles: true, cancelable: true,
           clientX: r.left + r.width / 2, clientY: r.top + r.height / 2, view: window};
['mousedown', 'mouseup', 'click'].forEach(t => btn.dispatchEvent(new MouseEvent(t, o)));
```

按钮要派发 `mousedown/mouseup/click` 三个事件，直接 `.click()` 有时不触发。

**成功标志**：`get_cookies` 能取到 `m_session_id`（36 字符）。
页面可能一直停在 passport 域并显示「登录中...」，**这是正常现象，不要等跳转**。

## 5. 落盘并验证

```sh
minis-browser-use get_cookies --tab_id <tab> --keywords m_session_id
# → 返回 env 文件路径

python3 scripts/modelscope/save_cookie.py --from-env <env 文件路径>
python3 scripts/modelscope/quota.py
```

`save_cookie.py` 会先打 balance 接口校验，**无效不覆盖**；能打出余额即恢复。
注意：它第一次运行会因缺配置报一行「缺少配置文件…请先登录」，随后立即写入并打印
`saved_to` 与 `balance`，这是正常流程。

## 6. 收尾

- 浏览器 `set_viewport --reset=true`，避免影响后续桌面版页面
- 关闭登录标签页
- `m_session_id` 只走 `get_cookies` → `--from-env` 这条链路，
  **绝不向用户索取 cookie、token 或让用户自己登录后把凭证发来**

---

## 常见错误

| 现象 | 原因 | 处理 |
|---|---|---|
| `execute_js` 返回 `null` | 用了 IIFE 包装，没有顶层 `return` | 改成顶层 `return` |
| 跨域页面 fetch `minis://` 失败 | 浏览器安全策略拦截 | 手机号由 shell 侧脚本注入，不经页面读文件 |
| 发码后仍有「请阅读并同意协议」 | 红条残留，不代表失败 | 以「N秒后重发」为准 |
| 点「获取验证码」无反应 | 协议未勾选 | 先点可见的 `input[type=checkbox]` |
| 点「登录」无反应 | 用了 `.click()` | 派发 mousedown/mouseup/click 三事件 |