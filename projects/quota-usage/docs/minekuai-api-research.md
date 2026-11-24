# 麦块云（Minekuai）接口调研

调研 2026-11-16，修订 2026-11-24。结论适用 `quota-usage` v1.2.0。
**一句话结论**：额度接口全在站点根域 `https://minekuai.cn/app/*`（无 `/api` 前缀），
纯 HTTP 可自动化；四条额度通道各自独立计费，`GET /app/token` 一次调用就能全拿到。

站点：`https://minekuai.cn`（麦块云 / Minekuai Cloud，四川麦块信息科技）
推理网关：`https://ai-api.minekuai.cn/v1`（OpenAI 兼容）

> 运行时需要查的参数速查（退出码、配置路径、通道编码含义）在技能内
> `quota-usage/references/minekuai-api.md`；本文只记调研过程与结论。

---

## 1. 站点性质

「一个账号打通全部产品」的多业务平台：文本模型 API + 云服务器（云服务器 / 算力服务器 / 物理服务器）。
文本模型本地部署（DeepSeek 系列，如 `deepseek-v4.1-flash-1017`）。

计费单位有三套，别混：

| 单位 | 含义 | 来源 |
|---|---|---|
| **鱼币**（coins / points） | 站内积分，签到 / 邀请 / 任务获得 | `/app/fish/mine`、`/app/wallet` |
| **token 额度** | 鱼币兑换或购买的 LLM 额度 | `/app/token` |
| **余额**（balance） | 真实货币（¥），充值后用来买 token 包 | `/app/balance` |

**2026-11-21 起商业模式变了**：站点公告（`/app/site/banner`）原文
> 因服务器算力不足 且部分用户批量注册后二次对接贩卖免费额度 因此目前关闭免费token使用

即：免费不限量已关闭，主推**付费按量 token**（1 元 = 1 亿 token，永久有效）。

---

## 2. 架构：三套域名，别再搞错

| 入口 | 域名 | 说明 |
|---|---|---|
| **业务 API** | `https://minekuai.cn/app/...` | 会员、余额、签到、鱼币、额度、Key、日志。同源、**无 `/api` 前缀** |
| **推理网关（真）** | `https://ai-api.minekuai.cn/v1/...` | OpenAI 兼容，返回标准 OpenAI 错误体 |
| 推理网关（旧） | `https://api.minekuai.cn/v1` | 现在返回业务包 `{code:401,msg:"未能读取到有效 token"}`，**不是推理接口** |

响应统一包成 `{code, msg, data}`，`code=200` 为成功。
**HTTP 状态码恒 200，业务错误也返回 200**，必须判 `body.code`。

---

## 3. 鉴权

- Bearer Token（不是 cookie）：`Authorization: Bearer <token>`
- token 存于 localStorage 的 `aivideo-auth`（zustand persist），另存 cookie 兜底
- 公开/半公开接口需要 `clientid` 头：`428a8310cd442757ae699df5d894f051`（member 端，前端写死）
- 可选设备头：`X-Device-Id` / `X-Device-Fp` / `X-Device-Auto`
- **JWT 7 天有效**，过期返回 `code=401 AUTH_EXPIRED`

### 登录（纯 HTTP，无 baxia 风控）

```
POST /app/auth/sms/send   {"phone":"1368xxxxxxx"}        # 60 秒冷却
POST /app/auth/login      {"phone":"...","smsCode":"123456","grantType":"sms"}
```

字段是 **`smsCode` + `grantType:"sms"`**，不是 `code`。试错路径：

```
{"phone","code"}                        → "Auth grant type cannot be blank"
{"phone","code","grantType":"sms"}      → "验证码不能为空"         ← code 未被识别
{"phone","smsCode","grantType":"sms"}   → "验证码已过期，请重新获取" ← 字段对了
```

---

## 4. 额度体系：四层，分开存

```
/app/token
├── today      {exchanged, bonus, used, remaining}     # 每日额度（鱼币兑换，当日 0 点清零）
├── permanent  {balance, totalIn, totalUsed}            # 永久额度（任务奖励，累计不重置）
├── remaining  = today.remaining + permanent.balance
├── exchange   {...}                                    # 鱼币→每日额度的兑换开关/上限
└── paid       {...}                                    # 付费按量额度（永久有效）
```

### 4.1 付费按量额度（paid）

**主力接口就是 `GET /app/token`，读 `data.paid`**，一次调用即得余额：

```json
"paid": {
  "group": "paygo", "groupName": "按量付费",
  "balance": 1179229601,         // ★ 付费余额（token），随调用实时减少
  "totalIn": 1200000000,         // 累计获得（含赠送）
  "totalUsed": 21241970,         // 累计消耗
  "buy": {"open": true, "unitYuan": 1, "unitTokens": 100000000,
          "minYuan": 1, "maxYuan": 2000, "official": {…}},
  "keys": 1,
  "packs": [{"name":"10 元 10 亿送 1 亿","priceYuan":10,
             "tokens":1000000000,"bonusTokens":100000000,"totalTokens":1100000000,
             "stock":50,"left":21,"soldOut":false,"mine":1,"canBuy":true}]
}
```

辅助接口：

| 用途 | 路径 | 关键字段 |
|---|---|---|
| 余额 | `GET /app/token` | `data.paid.balance / totalIn / totalUsed` |
| 购买记录 | `GET /app/token/paid/orders?page=1&size=20` | `rows[].{orderNo,state,amountYuan,tokens,bonusTokens,packName,paidTime,payChannel}` |
| 会员档额度（含付费余额镜像） | `GET /app/api-member/quota` | `paidBalance`、`groupCode`、`overflowToPaid` |
| 额度流水 | `GET /app/token/logs?page=1&size=50` | `rows[].{type,scope,delta,balanceAfter,coins,remark}` |
| 售卖开关 | `GET /app/site/sales` | `tokenPaid.{open,message}`、`tokenExchange.{open,message}` |
| 分组说明 | `GET /app/groups` | `code=paygo` 描述：1 元 = 1 亿 token，永久有效，不限会话 |

**关键结论：**

- **消耗不写入 `/app/token/logs`**（流水只记 buy / exchange / task 三类），余额只能从 `paid.balance` 读。
  逐笔消耗去 `GET /app/llm/requests`，每条带 `groupCode: "paygo"`。
- `paygo` 明细加总与 `paid.totalUsed` 相差约 **2.5%**，原始 token 与计费 token 接近 1:1，
  明细加总可直接当扣费额用。
- 余额几十分钟就能看到明显下降（对话本身在烧），用它算消耗速率最准。

### 4.2 每日额度（day）

鱼币签到 → 兑换 5000 万 token/天（10 鱼币），**当日有效、0 点清零**。
`exchange.open=false` 时兑换通道关闭（当前文案：「算力不足，按量额度兑换暂停。」）。
`exchange.dailyCap` 是真正的每日上限（50000000），`today.exchanged + bonus` 是今日实际到账。

### 4.3 永久额度（perm）

新手任务奖励（实名 5000 万、首次调用 1000 万、绑 QQ 1000 万），累计不重置。
`totalIn` 为 7000 万，与 `balance + totalUsed` 严格闭合。

### 4.4 其他钱与积分

| 接口 | 字段 |
|---|---|
| `GET /app/balance` | `balance`（¥，字符串） |
| `GET /app/wallet` | `giftPoints` / `paidPoints` / `heldPoints` / `totalPoints` |
| `GET /app/wallet/logs` | `pool` ∈ `gift`/`paid`，`changePoints`，`type` 如 `checkin` / `token_exchange` |
| `GET /app/fish/mine` | `coins`、`groupName`、`limits`（上下文 / 会话数）、`plan` |

---

## 5. 通道标记与消耗归属（2026-11-24 实测）

调用明细 `/app/llm/requests` 的 `groupCode` 有四个值：

| groupCode | 含义 | 对应额度池 |
|---|---|---|
| `default` | Lite 免费档 | 今日池（每日兑换的额度） |
| `lite_token` | Lite · 按量 | **永久池**（任务奖励的额度） |
| `paygo` | 按量付费 | 付费池 |
| `api_member` | Pro | 会员档额度 |

验证方法与结论：

- 永久池 `totalUsed` = 1524.11 万，而 11-17~11-19 三天 `lite_token` 合计 1475.82 万，
  差额落在更早的消耗上，说明永久池消耗在日志里全部标为 `lite_token`；
- 18 天窗口内 `default` 记录为 **0 条**，今日池 `used` 恒为 0（兑换通道关闭，池内无额度）；
- 11-15、11-16 在 `daily` 有 394 / 648 次调用，但明细最早只到 11-17，说明今日池的调用不写入明细
  （或更早的数据已清理）。

实时验证：50 秒对话期间，`today.used` 与 `permanent.totalUsed` 完全不动，
只有 `paid.totalUsed` 增长约 9.7 万 —— 三条通道各扣各的账。

`/app/llm/requests/daily` 的 `?groupCode=` / `?group=` 参数**被服务端忽略**，
传与不传结果完全一致，所以按通道拆分只能用明细分页聚合。

---

## 6. 完整接口清单（从前端 bundle 提取）

bundle：`/assets/index-6vWU7u8a.js`，提取 `/app/*` 共 50+ 条：

```
/app/addon/{buy,items,logs,mine}
/app/api-member  /app/api-member/{plan-change,quota}
/app/apikeys
/app/auth/{impersonate,login,logout,password/reset,register,sms/send}
/app/balance  /app/balance/logs
/app/cdk/redeem
/app/checkin
/app/fish/{logs,mine,tiers}
/app/groups
/app/inbox  /app/inbox/{read-all,unread-count}
/app/invite/{check,list,mine,rebates,rebates/claim,rebates/summary}
/app/llm/{models,models/public,rank,relay,requests,requests/daily,requests/hourly,requests/summary,stats/live}
/app/member/me  /app/member/password  /app/member/password/code
/app/recharge  /app/recharge/options
/app/reseller  /app/reseller/apply
/app/site/{banner,sales}
/app/token  /app/token/{exchange,logs,mode,tasks}
/app/token/paid/orders
/app/video/{limits,models,models/public,quote,tasks}
/app/wallet  /app/wallet/logs
```

**不存在**的猜测路径（都返回 404 包）：`/app/token/paid`、`/app/token/paygo`、`/app/token/quota`、
`/app/token/detail`、`/app/token/packs`、`/app/paygo`、`/app/overview`、`/app/user/info`、`/app/account`、
`/app/pay/orders`、`/app/order/list`、`/app/recharge/records`。

方法限制：`/app/token/mode`、`/app/cdk/redeem` 只接受非 GET（返回 405 包）。

### 会员档位（`/app/fish/tiers`）

| 档 | group | 上下文 | 会话 | 签到积分 | 连签加成 |
|---|---|---|---|---|---|
| Lite | default | 256K | 1 | 10 | 0% |
| Go / Plus / Pro | go / plus / api_member | 512K | 不限 | 15 | +50% |
| Max | max | 640K | 不限 | 15 | +50% |
| Ultra | ultra | 720K | 不限 | 15 | +50% |

附加包（`/app/addon/items`，鱼币买）：`priority` 高峰优先（15 币/天、70 币/7 天）、
`ctx` 上下文扩到 320K（20 币/天、100 币/7 天，只限 Lite）。

---

## 7. 踩坑

| 现象 | 原因 |
|---|---|
| `api.minekuai.cn/app/*` 全 401 | 业务 API 在站点根域 `minekuai.cn/app/*` |
| `minekuai.cn/api/app/*` 返回 HTML | 无 `/api` 前缀，SPA 兜底 index.html |
| 业务错误返回 HTTP 200 | 必须判 `body.code`，不是 HTTP 码 |
| 登录字段 `code` 报错 | 要用 `smsCode` + `grantType:"sms"` |
| 兑换显示「鱼币不足」但账户有 10 币 | 兑换通道关闭时 `unitsLeft=0`，要看 unitsLeft 而不是币数 |
| `paid.balance` 一直在掉但日志无记录 | 消耗不写入 `/app/token/logs` |
| `minekuai.com` 是另一个站 | 「麦块联机」游戏服，与麦块云无关 |
| `curl` 发码 401 | 打到了 `api.minekuai.cn`，应走 `minekuai.cn/app/auth/sms/send` |
| 分页只拿到第一页 | `/app/llm/requests` 认 `pageNum`+`pageSize`，`page`/`current`/`offset` 被静默忽略 |
| `render()` 报 KeyError 'nickname' | 变量解包时 `s` 同当 stats 和 user 用，重名；改用 `usr` |

---

## 8. 待验证

- [ ] `POST /app/token/paid/orders` 购买下单的 body 与支付回调（**涉及扣款，未经用户同意不测**）
- [ ] 永久额度在 `paygo` 分组下是否仍可被消耗（近 14 天 `lite_token` 记录为 0，疑似已停用）
- [ ] `PUT /app/token/mode` 的取值（auto/manual）对两个池分配的影响
- [ ] `paid.balance` 归零时的行为：直接拒请求，还是回落到永久额度
- [ ] `/app/token/tasks`、`/app/invite/*` 里是否还有未领的赚额度任务