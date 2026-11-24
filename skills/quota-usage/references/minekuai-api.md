# 麦块云（Minekuai）运行时速查

> 只放脚本运行时需要查的参数与字段。完整调研过程（接口清单、额度体系推导、踩坑实录）
> 在工程层 `docs/minekuai-api-research.md`，不随技能发布。

站点：`https://minekuai.cn` ｜ 业务 API 前缀 `/app/*`（无 `/api`）
推理网关：`https://ai-api.minekuai.cn/v1`（`api.minekuai.cn/v1` 已不是推理接口）
配置：`/var/minis/shared/mk-quota/config.json`（`MK_CONFIG` 可覆盖，0600）
登录：纯 HTTP，`scripts/minekuai/login.py --phone <号>`

## 关键接口

| 用途 | 路径 | 主要字段 |
|---|---|---|
| 额度总览 | `GET /app/token` | `today` / `permanent` / `remaining` / `exchange` / `paid` |
| 每日额度 | 同上 `today` | `exchanged` `bonus` `used` `remaining` |
| 永久额度 | 同上 `permanent` | `balance` `totalIn` `totalUsed` |
| 付费额度 | 同上 `paid` | `balance` `totalIn` `totalUsed` `buy` `packs` |
| 签到 | `GET/POST /app/checkin` | `checkedIn` `awardedToday` `streakDays` `nextBonusInDays` |
| 兑换 | `POST /app/token/exchange` | `units` `tokens` `coinsLeft` `today{…}` |
| 鱼币 | `GET /app/fish/mine` | `coins` `groupName` `limits` `plan` |
| 现金 | `GET /app/balance` | `balance`（字符串，单位元） |
| 会员 | `GET /app/member/me` | `nickname` `phoneMasked` `apiBanned` |
| 调用统计 | `GET /app/llm/requests/summary` | `requests` `failed` `inputTokens` `cacheRate` |
| 按日统计 | `GET /app/llm/requests/daily?days=7` | `daily[].{date,requests,inputTokens,cacheReadTokens,outputTokens}` |
| 调用明细 | `GET /app/llm/requests` | `rows[].{createTime,groupCode,apiKeyPrefix,inputTokens,cacheReadTokens,outputTokens}` |
| 购买记录 | `GET /app/token/paid/orders` | `rows[].{amountYuan,tokens,packName,paidTime}` |
| 售卖开关 | `GET /app/site/sales` | `tokenPaid.open` `tokenExchange.open` |
| 站点公告 | `GET /app/site/banner` | `title` `content` `level` |

## 字段口径

- `today` 每天 0 点清零，**只保留当天**，无法查历史日粒度
- `permanent.totalUsed` 单调累计，同样没有日粒度
- `exchange.dailyCap`（50000000）才是每日额度上限；`today.exchanged + bonus` 是今日实际到账
- `exchange.unitsLeft` 为 0 表示当前不可兑换（通道关闭或鱼币不足），**判断能否兑换看它，不看币数**
- `exchange.open` 为 false 时 `pausedMessage` 给出平台侧原因
- `paid.buy.open` 为 false 时暂停售卖，原因是算力不足一类，不是本地错误

## 通道编码（`groupCode`）

| 值 | 含义 | 对应池 |
|---|---|---|
| `default` | Lite 免费档 | 今日额度 |
| `lite_token` | Lite · 按量 | 永久额度 |
| `paygo` | 按量付费 | 付费额度 |
| `api_member` | Pro | 会员额度 |

按通道统计消耗只能走 `GET /app/llm/requests` 明细聚合（`daily` 的 `groupCode` 参数被服务端忽略）。
`scripts/minekuai/quota.py` 的 `channel_usage()` 做的就是这个：按 `pageNum` 翻页拉明细，
按 `groupCode` 分池累加，输出「今日」与「近 3 天」两个窗口。今日池只有今日维度
（每天清零，不存在跨天概念），所以 `render()` 只给永久池和付费池挂「近 3 天」。

## 分页参数（两套，不一致）

| 接口 | 参数 |
|---|---|
| `/app/llm/requests` | **`pageNum` + `pageSize`**（传 `page` 会被静默忽略，永远返回第一页） |
| `/app/token/logs`、`/app/token/paid/orders`、`/app/balance/logs` | `page` + `size` |

## 退出码

`0` 正常 ｜ `1` 网络/接口错误 ｜ `2` 需人工介入（业务失败、已签到未兑换）｜
`3` 登录态失效（token 7 天过期）｜ `4` 配置缺失

## 已知限制

- token 7 天有效，过期需重跑 `login.py --phone`
- 免费不限量自 2026-11-21 关闭；兑换通道当前被平台暂停（`exchange.open=false`）
- 消耗不写进 `/app/token/logs`，只能从 `paid.balance` 或调用明细推算
- 业务错误也返回 HTTP 200，必须判 `body.code`