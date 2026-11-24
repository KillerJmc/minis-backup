# 七牛（Qiniu AI Inference）接口调研

调研 2026-11-21，修订 2026-11-24。结论适用 `quota-usage` v1.2.0。
**一句话结论**：额度接口只需一个 Cookie（`PORTAL_SESSION`），纯 HTTP 可读；
但**活动额度接口的 `used` 字段恒为 0**，真实消耗必须走 `v3/stat/new`（单位是 K token，要 ×1000）。

站点：`https://portal.qiniu.com` ｜ 模型页：`/ai-inference/model?id=qiniu/conatus-free`
API 域名：`https://api.qnaigc.com/v1` ｜ 额度接口走 `portal.qiniu.com/api/proxy`

> 运行时速查在技能内 `quota-usage/references/qiniu-api.md`；
> 登录流程在 `quota-usage/references/qiniu-relogin.md`。

---

## 1. 当前用的免费活动

`qiniu/conatus-free`（1024-free 活动）：每日 **1 亿 token**，0 点重置，
用完请求被拒且**不扣账户余额**。活动期 2026-10-24 ~ **2026-11-30**。

---

## 2. 鉴权

只需要**一个 Cookie：`PORTAL_SESSION`**（124 字符）。
`SSID` / `PORTAL_UID` 都不是必需的（实测去掉后接口照常返回）。

登录最省事的是账号密码（`https://sso.qiniu.com/` 的「账号密码」tab），
实测无图形验证码；**微信登录不可用**（小程序白屏），别再试。

---

## 3. 接口

| 用途 | 路径 | 说明 |
|---|---|---|
| 活动额度 | `free-model-campaigns/<id>/quota` | `used` **恒为 0**，不可信 |
| 真实消耗 | `v3/stat/new` | 单位 **K token**，需 ×1000 |
| Key 汇总 | `v3/apikeys?with_quota=true` | 含 `totalTokens` |

`v3/stat/new` 需要按时间区间查询，统计口径与活动额度的重置点（0 点）对齐。

---

## 4. 踩坑

| 现象 | 原因 |
|---|---|
| 额度显示「已用 0」但明明在用 | 活动额度接口的 `used` 字段服务端未统计，必须走 `stat/new` |
| 消耗数字差了 1000 倍 | `stat/new` 单位是 K token |
| 微信登录进去白屏 | 小程序端已坏，不要走这条路 |
| 带上 SSID / PORTAL_UID 仍失败 | 不是必需的，关键只有 `PORTAL_SESSION` 一个 |

---

## 5. 待验证

- [ ] 活动 2026-11-30 到期后，`conatus-free` 是否下架、额度是否清零
- [ ] 换用付费 Key 时额度口径是否变化