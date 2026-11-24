# 魔搭登录态失效 → 重新登录

`quota.py` 退出码 `3`（`AUTH_EXPIRED`）时执行本流程。全程约 1–2 分钟，只发 1 条短信。

> 为什么必须走浏览器：短信接口 `/newlogin/sms/send.do` 由阿里 baxia 风控保护，放行条件是「JS 现场签名 + `_uab_collina` 与真实 TLS 指纹一致」。python / curl / curl_cffi 指纹伪造 / jsdom 复算全部被 `RGV587` 拦截（handshake 与 TLS 必须同源），**已实测穷尽**。所以只用真浏览器点两次，其余（校验、落盘）仍走脚本。

## 0. 前置

- 手机号：优先取 `config.json` 的 `phone`，没有就问用户（一次即可，之后会存下）。
- 浏览器必须是**移动形态**：`set_user_agent mobile_safari` + `set_viewport 390x844`。
  桌面 UA 打开 `/login` 会把表单渲染进 **passport 的跨域 iframe**，主页面 JS 操作不到。

## 1. 取得 passport 登录页（同源，可直接操作 DOM）

```js
// 在 https://modelscope.cn/login 上执行，取出 iframe 真地址
document.querySelector('iframe').src
// → https://passport.modelscope.cn/mini_login.htm?lang=zh_CN&appName=modelscope&...
```

直接 `navigate` 到这个 `passport.modelscope.cn/mini_login.htm?...` 地址。
导航后页面标题应是「登录」，且 `document.querySelectorAll('input')` 能取到
`请输入手机号` / `请输入验证码` / `nc_1_captcha_input` / `checkbox`。

## 2. 填手机号并取验证码

```js
const set=(el,v)=>{const s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
  s.call(el,v);el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}))};
set([...document.querySelectorAll('input')].find(i=>(i.placeholder||'').includes('手机号')), 'PHONE');
const cb=document.querySelector('input[type=checkbox]'); if(cb && !cb.checked) cb.click();
[...document.querySelectorAll('button,div,span,a')].filter(e=>e.innerText.trim()==='获取验证码').pop().click();
```

- 成功标志：按钮文案变「N秒后重发」，页面提示「短信验证码已发送」。
- 底层：`POST passport.modelscope.cn/newlogin/sms/send.do?appName=modelscope&fromSite=90`
  （body 含 `loginId`、`phoneCode=86`、`countryCode=CN`、`codeLength=6`、`ua=<baxia 现场令牌>`，那个 `ua` 无法离线生成）。
- **60 秒冷却**：重复点击会失败，等倒计时结束再点。
- 若返回 punish 页 / `RGV587`：立即停手（继续试会升级风控），30 分钟后再来。

## 3. 用户给验证码 → 提交登录

用 `user_ask` 向用户要 6 位码，然后把码填进去点登录：

```js
set([...document.querySelectorAll('input')].find(i=>(i.placeholder||'').includes('验证码')), 'CODE');
[...document.querySelectorAll('button,div,span,a')].filter(e=>e.innerText.trim()==='登录').pop().click();
```

成功标志：标签页跳到 `https://modelscope.cn/home`（标题「首页 - ModelScope 魔搭社区」）。
若仍停在 passport 页：多为验证码错误/过期，重发一次再试。

## 4. 落盘并验证

```
1) browser_use get_cookies  tab=<当前 tab>  keywords=m_session_id   → 得到 env 文件路径
2) python3 /var/minis/skills/quota-usage/scripts/modelscope/save_cookie.py \
        --from-env <env 文件路径> --phone <手机号>
3) python3 /var/minis/skills/quota-usage/scripts/modelscope/quota.py
```

`save_cookie.py` 会先打 balance 接口校验，**无效不覆盖**，成功时打印新余额；第 3 步能打出余额即恢复。

## 5. 收尾

- 记得把浏览器 `set_viewport` 复位（`reset=true`），避免影响后续桌面版页面（如 `modelscope.cn/magicube/usage` 需要 1440x900 才显示魔粒面板）。
- 若用户是在自己设备上登录的，也可让他把 `m_session_id` 直接发来，用
  `save_cookie.py --value <值> --phone <号>` 一步到位，无需走上面的浏览器流程。