# 妙词元（api.miaotoken.cn）运行时速查

> 只放脚本运行时需要查的参数与字段。完整调研（计费公式、1789 条复算、踩坑）
> 在工程层 `docs/miaotoken-tech.md`，不随技能发布。

站点：`https://api.miaotoken.cn`（New API v1.0.0-rc.22）
配置：`/var/minis/shared/quota/miaotoken.json`（`MT_CONFIG` 可覆盖，0600），只存 `refresh` / `user_id` / `saved_at`
账号：环境变量 `QUOTA_MIAOTOKEN_CRED`，格式 `账号；密码`（分隔符可用中英文分号或空格）
登录：`python3 scripts/miaotoken/quota.py --login`

## 额度换算

| 项 | 值 |
|---|---|
| `quota_per_unit` | 500 000 |
| 现金（元） | `quota ÷ 500 000` |
| 汇率 | 1 元 = 1 额度单位 |

## 鉴权

```
密码 --POST /api/user/login--> new_api_refresh cookie（30 天）
cookie --POST /api/user/auth/refresh--> access_token（15 分钟，同时下发新 cookie）
access_token + New-Api-User --> 业务接口
```

| 要点 | 说明 |
|---|---|
| 登录体 | `{"username": "<用户名或邮箱>", "password": "<密码>"}` |
| 刷新必须带 | `Origin: https://api.miaotoken.cn` + `Referer`，否则 403 `AUTH_ORIGIN_FORBIDDEN` |
| refresh 单次有效 | 每次刷新后旧值立即失效（`401 AUTH_SESSION_REVOKED`），必须原子写回 |
| 调用头 | `Authorization: Bearer <token>` + `New-Api-User: <user.id>` |
| 限流 | 连续登录 429，`retry-after: 90` |
| 磁盘只存 | `refresh` + `user_id`，不存密码、不存 access_token |

配置路径：`/var/minis/shared/quota/miaotoken.json`（可用 `MT_CONFIG` 覆盖），权限 0600。

## 接口

| 用途 | 路径 |
|---|---|
| 账户额度 | `GET /api/user/self` → `quota`（剩余）/ `used_quota`（已用） |
| 调用日志 | `GET /api/log/self?type=2&p=<页>&page_size=<n>` |
| 定价 | `GET /api/pricing`（免鉴权） |
| 令牌列表 | `GET /api/token/?p=1&size=<n>` |
| 站点状态 | `GET /api/status`（免鉴权） |

## 日志字段

| 字段 | 含义 |
|---|---|
| `prompt_tokens` | 输入总量（含缓存） |
| `completion_tokens` | 输出 |
| `created_at` | 秒级时间戳 |
| `model_name` | 模型 |
| `other` | JSON 字符串，含 `cache_tokens`、`group_ratio`、`expr_b64` |

**三类 token**：未命中 = `prompt_tokens − cache_tokens`，缓存读 = `cache_tokens`，输出 = `completion_tokens`。

OpenAI 系**没有缓存写**（那是 Anthropic 字段）。

## 分页

`p` 是 1-based，**`p=0` 与 `p=1` 返回同一页**。从 1 开始并按 `id` 去重。

## 单价

```
表达式计费：¥/百万 = 系数 × 分组倍率      （系数取 billing_expr 的 tier("base", p * X)）
倍率计费：  ¥/百万 = model_ratio × 分组倍率 × 2
```

分组倍率取该模型最近一条日志的 `group_ratio`（站点实际生效值），不要用 `enable_groups` 猜。

## 输出口径

| 字段 | 算法 | 依赖模型 |
|---|---|---|
| 已用 | 全部日志三类累加 | 否 |
| 今日 / 近 3 天 | 同批日志按时间过滤累加 | 否 |
| 剩余 | `quota ÷ 500000 ÷ 输入单价 × 100 万` | 是 |
| 现金 | `quota ÷ 500000` | 否 |

基准模型 = 近 3 个**有数据**的日期中 token 用量最多者。

不输出「总量」：已用是实测、剩余是折算，口径不同。

## 退出码

| 码 | 含义 |
|---|---|
| 0 | 正常 |
| 1 | 网络或业务错误 |
| 3 | 登录态失效，需 `--login` |
| 4 | 缺配置 |
| 5 | 触发限流（90 秒后重试） |