# 七牛（Qiniu AI Inference）运行时速查

> 只放脚本运行时需要查的参数与字段。完整调研（活动详情、单位换算坑）
> 在工程层 `docs/qiniu-api-research.md`，不随技能发布。

站点：`https://portal.qiniu.com` ｜ API：`https://api.qnaigc.com/v1`
额度接口：`portal.qiniu.com/api/proxy/...`
配置：`/var/minis/shared/quota/qiniu.json`（`QN_CONFIG` 可覆盖，0600）
登录：只需要一个 Cookie `PORTAL_SESSION`，流程见 [`qiniu-relogin.md`](qiniu-relogin.md)

## 关键接口

| 用途 | 路径 | 主要字段 |
|---|---|---|
| 活动额度 | `api/proxy/free-model-campaigns/<id>/quota` | `total` / `used`（**used 恒为 0，别信**） |
| 真实消耗 | `api/proxy/v3/stat/new` | 返回 **K token**，需 ×1000 |
| Key 汇总 | `api/proxy/v3/apikeys?with_quota=true` | `totalTokens` |

## 输出结构

```
七牛额度

💰 额度

- 已用 A · 剩余 B · 总量 C
- 今日消耗 D · 近 3 天消耗 E

💳 账户

- 到期 YYYY-MM-DD
- 余额 ¥N
```

- 到期时间取 `availability.end_at`（`2026-12-30T23:59:59+08:00`，取前 10 位）
- 账户区不写模型、重置时间、Key 累计；平台无签到，不写签到行

## 额度口径

- 当前免费活动模型 `qiniu/conatus-free`：每日 **1 亿 token**，0 点重置
- 用完直接拒请求，**不扣账户余额**
- 真实消耗**必须**走 `v3/stat/new`，活动额度接口的 `used` 恒为 0
- `v3/stat/new` 的单位是 **K token**，乘 1000 才是 token

## 退出码

`0` 正常 ｜ `1` 网络/接口错误 ｜ `2` 需人工介入 ｜ `3` 登录态失效 ｜ `4` 配置缺失

## 已知限制

- 活动期 2026-10-24 ~ **2026-11-30**，到期后模型可能下架
- 没有签到接口，额度由服务端自动发放；`checkin.py` 只做可用性检查
- 微信登录不可用（小程序白屏），只能账号密码或已有 Cookie