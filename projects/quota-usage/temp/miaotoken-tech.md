# 妙词元（api.miaotoken.cn）技术文档

调研 2026-11-25/26。结论均经真实账号验证。

---

## 一、站点

| 项 | 值 |
|---|---|
| 域名 | `https://api.miaotoken.cn` |
| 程序 | New API v1.0.0-rc.22 |
| 额度单位 | 500 000 quota = ¥1 |
| 汇率 | 1 元 = ¥1 额度 |
| 登录方式 | 用户名或邮箱 + 密码 |
| 验证码登录 | 无 |
| OAuth | 全部关闭 |

`/api/status` 与 `/api/pricing` 无需鉴权即可读取。

---

## 二、鉴权

### 三段式

```
密码 ──登录──> 刷新令牌（30 天） ──刷新──> 访问令牌（15 分钟）
```

### 登录

```
POST /api/user/login
Content-Type: application/json

{"username": "<用户名或邮箱>", "password": "<密码>"}
```

响应体 `data` 字段：

| 字段 | 用途 |
|---|---|
| `access_token` | 访问令牌，15 分钟有效 |
| `access_expires_at` | 过期时间戳 |
| `user.id` | 用户 ID，调用时必带 |
| `session` | 会话元信息 |

响应头带 `Set-Cookie: new_api_refresh=...; Path=/api/user/auth; Max-Age=2591999`。

`Path=/api/user/auth` 意味着该 cookie 只能用于刷新接口，不能直接调用业务接口。

**限流**：连续登录返回 429，响应头 `retry-after: 90`。

### 刷新

```
POST /api/user/auth/refresh
Origin: https://api.miaotoken.cn
Referer: https://api.miaotoken.cn/
Cookie: new_api_refresh=<值>

{}
```

**必须带 `Origin`**，缺失或错误返回 403 `AUTH_ORIGIN_FORBIDDEN`。

响应返回新的 `access_token`，同时 `Set-Cookie` 下发新的刷新令牌。

**刷新令牌单次有效**：每次刷新后旧值立即失效，必须原子写回磁盘。用旧值重试返回 401 `AUTH_SESSION_REVOKED`。

### 调用

```
GET <路径>
Authorization: Bearer <access_token>
New-Api-User: <user.id>
Accept: application/json
```

`New-Api-User` 缺失时返回 401。

### 存储

只落盘刷新令牌与 `user_id`，不存密码、不存访问令牌。

```json
{
  "refresh": "new_api_refresh=...",
  "user_id": 1202,
  "username": "KillerJmc",
  "email": "killerjmc@163.com",
  "saved_at": "2026-11-26 15:00:00"
}
```

文件权限 0600。

---

## 三、接口

### 账户

```
GET /api/user/self
```

| 字段 | 含义 |
|---|---|
| `quota` | 剩余额度 |
| `used_quota` | 已用额度 |
| `request_count` | 累计请求数 |
| `username` / `email` / `group` | 账户信息 |

三个额度字段的关系：`quota + used_quota = 累计充值额度`。

### 调用日志

```
GET /api/log/self?type=2&p=<页码>&page_size=<每页>&start_timestamp=<秒>&end_timestamp=<秒>
```

| 参数 | 说明 |
|---|---|
| `type=2` | 消费记录 |
| `p` | 页码，**从 1 开始**；`p=0` 与 `p=1` 返回同一页 |
| `page_size` | 每页条数，上限 100 |
| `start_timestamp` / `end_timestamp` | 时间过滤，秒级时间戳 |

`p=0` 与 `p=1` 重复，必须从 1 开始并按 `id` 去重。

单条记录的关键字段：

| 字段 | 含义 |
|---|---|
| `prompt_tokens` | 输入总量（含缓存） |
| `completion_tokens` | 输出 |
| `quota` | 本条扣费额度 |
| `model_name` | 模型 |
| `created_at` | 时间戳 |
| `other` | JSON 字符串，含计费快照 |

`other` 内嵌字段：

| 字段 | 用途 |
|---|---|
| `expr_b64` | 当时的计费表达式（base64） |
| `group_ratio` | 当时的倍率 |
| `cache_tokens` | 缓存读取 token 数 |
| `matched_tier` | 命中档位 |
| `cache_ratio` / `completion_ratio` / `model_ratio` | 当时的倍率参数 |

核对历史扣费必须用 `other` 快照，不能用当前 `/api/pricing`。

### 其他

| 接口 | 内容 |
|---|---|
| `GET /api/token/?p=1&size=<n>` | API Key 列表 |
| `GET /api/user/topup/self?p=0&page_size=<n>` | 充值记录 |
| `GET /api/data/self?start_timestamp=&end_timestamp=` | 按日聚合，时间跨度上限 1 个月 |
| `GET /api/user/self/groups` | 分组倍率表 |
| `GET /api/pricing` | 全部模型定价，免鉴权 |

---

## 四、计费

### 基础换算

| 换算 | 公式 |
|---|---|
| 人民币 → 额度 | 额度 = 人民币 × 500 000 |
| 额度 → 人民币 | 人民币 = 额度 ÷ 500 000 |

### token 分三类

一次请求的输入只有两部分，互不重叠，合计等于 `prompt_tokens`。

| 类别 | 统计方式 |
|---|---|
| 未命中输入 | `prompt_tokens − cache_tokens` |
| 缓存读 | `cache_tokens` |
| 输出 | `completion_tokens` |

**无缓存写。** OpenAI 的 usage 只上报缓存读 `cached_tokens`；缓存写 `cache_creation_tokens` 是 Anthropic 的字段。站点表达式里的 `cc` 项属通用写法，GPT 流量下恒为 0。

### 分组倍率

| 分组 | 倍率 |
|---|---|
| codex特价 | 0.1 |
| grok | 0.15 |
| codex-企业 | 0.2 |
| claude特价 | 0.2 |
| codex_官key | 0.3 |
| codex不降智 | 0.3 |
| claude-企业 | 1.2 |

### 表达式计费（8 个 GPT 模型）

```
额度 = (未命中×A + 输出×B + 缓存读×C + 缓存写×D) ÷ 1 000 000 × 500 000 × 分组倍率
     = (未命中×A + 输出×B + 缓存读×C + 缓存写×D) × 0.5 × 分组倍率

人民币/百万 = 系数 × 分组倍率
```

A/B/C/D 取自 `billing_expr`，`prompt_tokens < 272 000` 走基础档，否则走长文档（价格翻倍）。

| 模型 | 档 | 输入 | 输出 | 缓存读 |
|---|---|---|---|---|
| gpt-5.5 | 基础 | 5 | 30 | 1 |
| | 长文 | 10 | 45 | 2 |
| gpt-5.6-sol | 基础 | 5 | 30 | 1 |
| | 长文 | 10 | 45 | 2 |
| gpt-5.6-terra | 基础 | 2.5 | 15 | 0.5 |
| | 长文 | 5 | 22.5 | 1 |
| gpt-6-sol | 基础 | 2 | 10 | 0.4 |
| | 长文 | 4 | 15 | 0.8 |
| gpt-6-astra | 基础 | 10 | 50 | 2 |
| | 长文 | 20 | 75 | 4 |
| gpt-6.1-sol | 基础 | 2 | 10 | 0.2 |
| | 长文 | 4 | 15 | 0.4 |
| gpt-6.2-sol | 基础 | 2 | 10 | 0.2 |
| | 长文 | 4 | 15 | 0.4 |
| gpt-6.2-astra | 基础 | 8 | 40 | 0.8 |
| | 长文 | 16 | 60 | 1.6 |

这 8 个模型的 `model_ratio` 字段不参与计费，仅作展示。

### 倍率制（codex-auto-review）

```
提示成本 = (prompt − 缓存读) + 缓存读×缓存倍率
输出成本 = 输出×输出倍率
额度 = (提示成本 + 输出成本) × 模型倍率 × 分组倍率
```

| 参数 | 值 |
|---|---|
| 模型倍率 | 2.5 |
| 输出倍率 | 6 |
| 缓存倍率 | 0.1 |
| 可用分组 | codex不降智（0.3） |

### 按次计费（6 个图像模型）

```
额度 = 每次价格 × 500 000 × 分组倍率 × 图片数
```

`gpt-image-2` 系列每次价格 1，仅 `codex-企业`（0.2）可用，即每张 ¥0.2。

---

## 五、输出格式

```
妙词元额度 · <用户名>（<邮箱>）

💰 额度

- 已用 <值> · 剩余 <值>（<模型> ¥<单价>/百万）
- 今日消耗 <值> · 近 3 天消耗 <值>

💳 账户

- 现金 ¥<值>
```

### 单位

| 条件 | 格式 |
|---|---|
| ≥ 1 亿 | `x.xx 亿` |
| < 1 亿 | `x.xx 万` |
| = 0 | `0` |

### 各字段口径

| 字段 | 算法 | 是否依赖模型 |
|---|---|---|
| 已用 | 日志三类累加 | 否 |
| 今日消耗 | 同批日志按当日过滤累加 | 否 |
| 近 3 天消耗 | 同批日志按三天窗口过滤累加 | 否 |
| 剩余 | 现金 ÷ 单价 × 1 000 000 | 是 |
| 现金 | `quota` ÷ 500 000 | 否 |

### 基准模型选取

1. 取近 3 个**有数据**的日期（不是近 3 个自然日）
2. 在这三天的记录中，取 token 用量最多的模型
3. 用该模型的未命中输入单价作为标尺

标尺单价 = 该模型 `billing_expr` 基础档的输入系数 × 当前分组倍率。

### 不输出总量

已用是混合模型的历史实测，剩余是单模型单价折算，两者口径不同，相加无意义。麦块云能做到三槽位，是因为它的额度本身就是 token。

---

## 六、验证

### 账户闭合

```
剩余 1 818 730 + 已用 13 181 270 = 15 000 000 quota
15 000 000 ÷ 500 000 = ¥30.00
```

充值记录合计：兑换码 ¥5 + ¥3×5 = ¥20，在线充值 ¥10，共 ¥30。

### 单条扣费

日志一条记录：`prompt_tokens` 50 813、`cache_tokens` 41 915、`completion_tokens` 78，模型 `gpt-6.1-sol`，倍率 0.1。

```
未命中 = 50 813 − 41 915 = 8 898
成本   = 8 898×2 + 78×10 + 41 915×0.2 = 26 959
额度   = 26 959 × 0.5 × 0.1 = 1 347.95 → 1 348
```

日志实记 1 348。

### 全量复算

1 789 条有扣费记录逐条复算：

| 模型 | 条数 | 超差 |
|---|---|---|
| gpt-5.6-sol | 987 | 0 |
| gpt-6.1-sol | 758 | 0 |
| gpt-5.6-terra | 29 | 0 |
| gpt-5.5 | 15 | 0 |

合计算得 13 181 225，实记 13 181 270，差 45（取整误差 0.0003%）。

### 已用构成

| 类别 | token | 花费 |
|---|---|---|
| 未命中输入 | 43 096 816 | ¥14.13 |
| 缓存读 | 144 706 587 | ¥10.24 |
| 输出 | 943 281 | ¥1.99 |
| 合计 | 188 746 684 | ¥26.36 |

缓存读占 token 总量 77%，占花费 39%。

---

## 七、踩坑

| 现象 | 原因 | 处理 |
|---|---|---|
| 登录后调用全 401 | 只拿到刷新令牌，`Path=/api/user/auth` | 先刷新换访问令牌 |
| 刷新 403 `AUTH_ORIGIN_FORBIDDEN` | 缺 `Origin` 头 | 补 `Origin` 与 `Referer` |
| 刷新后旧 cookie 失效 | 令牌单次有效，每次轮换 | 刷新后立即原子写回 |
| 连续登录 429 | 限流 90 秒 | 靠刷新令牌，不反复登录 |
| 日志条数对不上 | `p=0` 与 `p=1` 同一页 | 从 1 开始并按 `id` 去重 |
| SSL 握手偶发超时 | 站点网络不稳 | 请求加重试 |
| 历史扣费算错 | 站点改过分组归属 | 用日志 `other` 里的快照 |

---

## 八、未验证

| 项 | 原因 |
|---|---|
| 长文档（≥272 000 token） | 实测最大 `prompt_tokens` 为 250 906 |
| 缓存写计费 | 1 789 条记录中该字段从未出现 |
| 倍率制（codex-auto-review） | 无使用记录 |
| 按次计费（6 个图像模型） | 无使用记录 |
