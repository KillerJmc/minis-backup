# 魔搭（ModelScope）接口调研

调研 2026-11-16，修订 2026-11-24。结论适用 `quota-usage` v1.2.0。
**一句话结论**：额度接口纯 HTTP 可读（三个 `/openapi/v1/magicubes/*`），但**登录必须走浏览器**
——短信接口由阿里 baxia 风控保护，离线方案已实测穷尽全部失败。

站点：`https://modelscope.cn` ｜ 额度页：`https://modelscope.cn/magicube/usage` ｜ 计费单位：**魔粒**

> 运行时速查在技能内 `quota-usage/references/modelscope-api.md`；
> 登录流程在 `quota-usage/references/modelscope-relogin.md`。

---

## 1. 鉴权

只认 Cookie **`m_session_id`**，Bearer token 无效。

登录必须走浏览器：短信接口由阿里 baxia 风控保护，要求 JS 现场签名与真实 TLS 指纹同源，
Python / curl / curl_cffi / jsdom 复算全部被 `RGV587` 拦截（已实测穷尽）。
所以只把「点两次」交给浏览器，校验与落盘仍走脚本。

---

## 2. 接口

`api_get()` 已剥掉 `{success, request_id, data}` 外层，返回 `data`。

| 用途 | 路径 |
|---|---|
| 余额 | `GET /openapi/v1/magicubes/balance` |
| 消耗/发放明细 | `GET /openapi/v1/magicubes/transactions?type=SPEND_CONFIRM,EXPIRE\|EARN&page=1&page_size=20` |
| 发放规则 | `GET /openapi/v1/magicubes/earn/rules` |

---

## 3. 「签到」不是签到

魔搭**没有**签到按钮，也没有 checkin 接口（`/magicubes/signin`、`/users/checkin`、
`/magicubes/daily` 全部 404）。

真实机制：**当天首次带登录态访问站点**时服务端判定发放。判据是 `earn/rules` 里
`category_key=daily` 的两条规则：

| rule_key | 标题 | 数量 | 有效期 |
|---|---|---|---|
| `daily_active` | 注册并登录 | 200 | 1 天 |
| `aliyun_bindlogin` | 绑定阿里云账号 | 50 | 1 天 |

所以自动签到的姿势是：读规则 → `today_remain > 0` 就 `GET /home` 触发 →
轮询规则直到到账。**200 / 50 都只有 1 天有效期**，隔天清零。

---

## 4. 计费

`DeepSeek-V4.1-Flash-1017` 属旗舰档 **2 魔粒/次调用**。
Minis 每个工具轮次 = 1 次 API 调用 = 2 魔粒，多轮探索很烧额度。

---

## 5. 踩坑

| 现象 | 原因 | 处理 |
|---|---|---|
| 刚重登后余额显示 0，页面却显示 250 | 旧 cookie 被踢的瞬间接口短暂返回空 | 等 cookie 刷新或用新 cookie 重打，**别误判成没额度** |
| 桌面 UA 打不开登录表单 | `/login` 把表单塞进 passport 跨域 iframe | 必须移动 UA + 390x844，直接 navigate 到 `mini_login.htm` |
| 默认是密码登录页 | 只有账号密码输入框 | 先点「短信登录」tab |
| `.click()` 不提交 | 页面停在「登录中...」 | 用 `MouseEvent` 派发 mousedown/mouseup/click 三连 |
| 短信 60 秒冷却 | 重复点「获取验证码」 | 等倒计时 |

---

## 6. 待验证

- [ ] 一次性任务还有 3 项各 50 粒没领：验证邮箱、编辑个人介绍、配置个人主页
      （可在 `earn/rules` 里按 rule_key 查状态）