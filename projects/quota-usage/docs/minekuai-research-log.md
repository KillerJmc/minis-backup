# 麦块云付费额度调研过程

2026-11-23 ~ 11-24。适用 `quota-usage` v1.2.x。
**一句话结论**：付费额度不需要新接口，`GET /app/token` 的 `data.paid` 一直就有；
真正花掉时间的是三件事——分页参数名错导致假结论、按通道统计被服务端忽略参数、以及判断永久池消耗藏在哪个 `groupCode` 里。

本文记调研**怎么走的**（试了什么、错在哪、怎么翻案的）。结论本身在
[`minekuai-api-research.md`](minekuai-api-research.md)。探测脚本在 `temp/research/minekuai/probes/`。

---

## 起点：登录态过期

第一次查额度直接 rc=3：`AUTH_EXPIRED 认证失败，无法访问系统资源`。token 7 天有效，上次登录是 11-16。

走 `login.py --phone` 纯 HTTP 重登，发码成功、输入验证码成功。**这一步没踩坑**，
因为 11-16 那次已经把字段试错过（`smsCode` + `grantType:"sms"`，不是 `code`）。

---

## 第一轮：大面积铺路径找付费额度接口

用 `probe_mk.py` 打了 17 条候选路径，看哪些存在：

| 结果 | 路径 |
|---|---|
| 200 有数据 | `/app/balance`、`/app/balance/logs`、`/app/token`、`/app/token/tasks`、`/app/wallet`、`/app/fish/mine`、`/app/fish/tiers`、`/app/member/me`、`/app/llm/requests/summary`、`/app/llm/stats/live` |
| 404「请求地址不存在」 | `/app/overview`、`/app/user/info`、`/app/account`、`/app/pay/orders`、`/app/order/list`、`/app/recharge/packages`、`/app/token/plans`、`/app/goods/list` |

**关键发现**：`/app/token` 的返回里有 `paid` 段，含 `balance` / `totalIn` / `totalUsed` / `buy` / `packs`。
也就是说付费额度的主力接口**第一轮就已经拿到了**，只是当时没意识到。

---

## 第二轮：多余的猜测（事后看是白跑）

以为付费额度该有独立接口，用 `probe_mk2.py` 又试了 18 条：

`/app/token/paid`、`/app/token/paygo`、`/app/token/quota`、`/app/token/detail`、
`/app/token/order/list`、`/app/token/orders`、`/app/token/records`、`/app/token/packs`、
`/app/paygo`、`/app/paygo/token`、`/app/llm/keys`、`/app/token/keys`、
`/app/pay/orders?pageNum=`、`/app/order/orders`、`/app/recharge/records`、
`/app/balance/yuan`、`/app/wallet/points`

**全部 404，只有两条例外**：

- `/app/token/logs` 通，返回 `scope` ∈ `paid`/`day`/`perm` 的流水
- `/app/apikeys` 通

这轮基本是浪费——明明 `paid` 已经在第一轮的响应里。**教训**：拿到一个总览接口后，
先把它返回的字段全看完再去找别的接口，别先假设「这个功能应该有专门端点」。

---

## 第三轮：从前端 bundle 反查，确认接口边界

不再猜路径，直接读前端源码。`curl https://minekuai.cn/` 拿到 `assets/index-6vWU7u8a.js`（727 KB），
正则提取 `"/app/` 开头的字符串，得到 50+ 条真实存在的路径。

这一步的价值是**确认边界**：猜了 18 条，真正存在但前两轮没试出来的只有
`/app/token/paid/orders`、`/app/site/sales`、`/app/api-member/quota`、`/app/recharge/options` 这几条。
其余猜测全部是臆造的。

同时确认了 `/app/token/mode`、`/app/cdk/redeem` 只接受非 GET（返回 405 包）。

---

## 第四轮：推理网关到底是哪个域名

Minis 里 provider 的 base URL 是 `https://ai-api.minekuai.cn`，但 11-16 的调研记的是
`api.minekuai.cn/v1`。两个都打了一遍：

| 地址 | 返回 |
|---|---|
| `ai-api.minekuai.cn/v1/models` | HTTP 401 + **标准 OpenAI 错误体** |
| `api.minekuai.cn/v1/models` | HTTP 200 + **业务包** `{code:401,msg:"未能读取到有效 token"}` |

结论：`ai-api.minekuai.cn` 才是推理网关，`api.minekuai.cn` 已经变成业务接口的另一个入口。
这也解释了为什么「今日剩余 0」不影响使用——会话实际走的是 `paygo` 分组。

---

## 翻案：一条假结论怎么产生的

这是整个调研最值得记的一段。

**当时的做法**：想按通道拆分消耗，于是翻页拉 `/app/llm/requests`：

```python
page = 1
while True:
    d = g(f'/app/llm/requests?page={page}&size=100')
    rows += d['rows']
    if len(rows) >= d['total']: break
    page += 1
```

**结果**：跑了 29 轮，收了 580 条，`groupCode` 全是 `paygo`。

**据此得出的结论**：「18 天窗口内 `default` 记录为 0 条，永久池消耗全部标为 `paygo`」。

**错在哪**：`page` 和 `size` 这两个参数名服务端根本不认，**永远返回第一页的 20 条**。
循环条件 `len(rows) >= d['total']` 里的 `total` 是真实总数（570），所以循环跑了 29 次，
每次都是同一页 —— 580 条其实是 20 条重复了 29 遍。

**怎么发现的**：后来为了核对另一个数字，打印了明细里最早和最晚的记录时间，
发现全部集中在今天，而 `daily` 显示 11-17 到 11-19 有大把调用。这不可能对。

**怎么验证翻页参数**：拿第一页头两条的 id 尾巴，对比不同参数下的第二页：

```
?page=2&size=20              → 911361, 180162   ← 与第一页相同，参数被忽略
?pageNum=2&pageSize=20       → 457538, 131521   ← 真的翻页了
?current=2&size=20           → 911361, 180162   ← 被忽略
?offset=20&limit=20          → 911361, 180162   ← 被忽略
```

**换成正确参数后的真实数据**：

| 日期 | 通道 | 原始 token | 请求数 |
|---|---|---|---|
| 11-17 | `lite_token` | 850.96 万 | 243 |
| 11-18 | `lite_token` | 9.93 万 | 17 |
| 11-19 | `lite_token` | 614.93 万 | 104 |
| 11-19 | `paygo` | 1672.42 万 | 86 |
| 11-21 | `paygo` | 331.43 万 | 37 |
| 11-23 | `paygo` | 596.55 万 | 85 |

于是原来的结论全反了：**永久池的消耗标记是 `lite_token`**，不是 `paygo`；
`default` 才是今日池，而它在窗口内确实一条都没有。

**教训**：
- 翻页不能只看「拿到了足够多的行」，要**对比相邻两页的首条 id**，确认真的换了页
- 循环里累加重复数据不会报错，只会静默给出一个看似完整的假结论
- 数字之间要互相校验（明细时间范围 vs `daily` 的时间范围），对不上就说明有环节错了

---

## 三条额度通道是独立计数的（实测）

为了回答「今天到底哪个池在扣账」，做了 50 秒的快照对比：期间保持对话（模型持续被调用）。

| 计数 | 起始 | 50 秒后 | 变化 |
|---|---|---|---|
| `today.used` | 0 | 0 | **0** |
| `permanent.totalUsed` | 15241069 | 15241069 | **0** |
| `paid.totalUsed` | 24274960 | 24371933 | **+96973** |

三个计数器各自独立，互不影响。这也直接证明了当前会话走的是付费通道。

---

## 按通道统计为什么只能手工聚合

想用 `daily?groupCode=paygo` 直接按通道取数，实测：

| 请求 | 返回 |
|---|---|
| `/app/llm/requests/daily?days=3` | 三天总量 |
| `/app/llm/requests/daily?days=3&groupCode=paygo` | **完全相同** |
| `/app/llm/requests/daily?days=3&group=paygo` | **完全相同** |
| `/app/llm/requests/summary?groupCode=paygo` | 全账号总量，未过滤 |

两个参数名都试过，服务端**静默忽略**，不报错也不生效。
所以按通道拆分只能靠 `/app/llm/requests` 明细分页聚合。

---

## 口径可靠性验证

用 `paygo` 明细加总与 `paid.totalUsed` 对账：

- 明细加总：1672.42 + 331.43 + 596.55 = **2600.40 万**
- `paid.totalUsed`：**2627.34 万**
- 差 1.0%（含抓取时间差，抓的时候还在产生新请求）

说明**原始 token 与计费 token 接近 1:1**，明细加总可以直接当扣费额用，误差在 3% 以内。
（早先一次对齐算是 2.5%，量级一致。）

---

## 免费池的日粒度：能算，但要绕

`today.used` 每天 0 点清零，服务器不存历史，所以**问「今日池近 3 天」本身没有意义**。

`permanent.totalUsed` 是单调累计，接口没给日粒度，但明细里的 `lite_token` 记录可以聚合出来：

- 永久池 `totalUsed` = 1524.11 万
- 11-17~11-19 的 `lite_token` 合计 = 1475.82 万
- 差额 48.29 万，落在 11-16 及更早（明细窗口之外）

11-15、11-16 在 `daily` 里有 394 / 648 次调用，但明细最早只到 11-17 00:00:07。
说明**今日池的调用不写入明细接口**，或者更早的数据已被清理。

---

## 还剩什么没做

- `POST /app/token/paid/orders` 的下单 body 结构与支付回调 —— **涉及扣款，未测**
- `paid.balance` 归零时的行为：拒请求还是回落到永久额度 —— 余额还够用几个月，等自然触及
- `PUT /app/token/mode` 的取值对两个池分配的影响 —— 未测
- 兑换通道恢复后 `default` 通道是否重新出现记录 —— 等平台恢复算力

---

## 探测脚本索引（`temp/research/minekuai/probes/`）

| 脚本 | 干了什么 |
|---|---|
| `probe_mk.py` | 第一轮 17 条路径扫描，找到 `/app/token` 含 `paid` |
| `probe_mk2.py` | 第二轮 18 条猜测，几乎全 404（教训：先看完已有响应） |
| `probe3.py` | 购买记录、售卖开关、分组说明 |
| `probe4.py` | 确认流水里不记消耗 |
| `probe5.py` / `probe6.py` | 附加包、模式开关、通道过滤参数 |
| `probe7.py` ~ `probe10.py` | 翻页与通道分布（**含那次假结论的复现**） |
| `probe11.py` / `probe12.py` | 14 天窗口、密钥字段 |
| `agg3.py` | 用正确分页参数聚合（翻案的那次） |
| `chk3.py` | 四种分页参数名的对比验证 |
| `dump.py` / `dump2.py` | 原始响应全量转储 |