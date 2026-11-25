# 妙词元（api.miaotoken.cn）用量查询技术方案

调研 2026-11-25。**已实测通过**，实现见 `temp/mt_quota.py`。

## 一、站点性质

| 项 | 值 |
|---|---|
| 站点名 | 妙词元（footer：妙词科技） |
| 类型 | **New API** v1.0.0-rc.22 |
| 域名 | `https://api.miaotoken.cn`（前端与 API 同域） |
| 计费 | `quota_per_unit = 500000` → **quota ÷ 500000 = 美元** |
| 显示 | `quota_display_type: USD`、`display_in_currency: true` |
| 验证码 | `turnstile_check: false` |
| 注册 | 开放，但需邮箱验证码 |
| 签到 | **无**（`checkin_enabled: false`） |

实测对账：账号 `quota + used_quota = 15000000`，正好 30.00 美元，单位换算确认无误。

## 二、登录方式（实测排除了全部免密选项）

| 方式 | 结果 |
|---|---|
| 用户名/邮箱 + 密码 | ✅ **唯一可用** |
| 邮箱验证码登录 | ❌ `/api/user/login/email` 404 |
| 短信验证码登录 | ❌ `/api/user/login/sms` 404 |
| GitHub / Discord / LinuxDO / OIDC | ❌ 全关 |
| Passkey | ❌ 关闭 |
| API Key | ✅ 但只能查该 Key 自身（`/api/usage/token/`），非账号级 |

登录字段：`{"username": ..., "password": ...}`。**`username` 既可填用户名也可填邮箱**——
源码 `DB.Where("username = ? OR email = ?", username, username)` 两字段都匹配
（`?` 是参数化占位符，不存在注入面）。实测 `{"email": ...}` 报 `Invalid parameters`，
说明 `email` 不是登录字段名。

## 三、鉴权链（关键，决定配置里存什么）

```
账号密码 ──POST /api/user/login──> new_api_refresh cookie（30 天）
refresh cookie ──POST /api/user/auth/refresh──> access_token（15 分钟）+ 新 refresh cookie
access_token + New-Api-User 头 ──> 业务接口
```

三条实测出来的硬约束：

1. **refresh 调用必须带 `Origin: https://api.miaotoken.cn`**，否则 403 `AUTH_ORIGIN_FORBIDDEN`。
2. **refresh cookie 单次有效**：每次刷新都会轮换，旧值立即失效（再用报 401
   `AUTH_SESSION_REVOKED`）。所以必须**刷新后立刻原子写回配置**，否则下一次查询就掉线。
3. **登录接口有速率限制**：连续登录返回 429，`retry-after: 90`。所以绝不能靠反复登录，
   必须复用 refresh cookie——这也是它 30 天有效期内唯一的正确用法。

结论：**磁盘上只存 refresh cookie 与 user_id，不存密码、不存 access_token。**

配置：`/var/minis/shared/mt-quota/config.json`（0600），字段
`refresh` / `user_id` / `username` / `email` / `saved_at`。

## 四、接口与字段

| 用途 | 接口 | 关键字段 |
|---|---|---|
| 额度 | `GET /api/user/self` | `quota`（剩余）、`used_quota`（已用）、`request_count`、`group`、`email` |
| 令牌列表 | `GET /api/token/` | `items[].{name, remain_quota, used_quota, unlimited_quota, expired_time}` |
| 调用日志 | `GET /api/log/self` | `items[].{id, created_at, model_name, quota, prompt_tokens, completion_tokens, type}` |
| 按日聚合 | `GET /api/data/self` | 按小时的行，字段 `created_at / model_name / token_used / count / quota` |
| 站点配置 | `GET /api/status` | `quota_per_unit`、`price`、各功能开关（**无需鉴权**） |

**总额 = `quota` + `used_quota`**（New API 的 `quota` 是余额，不是总额）。

## 五、坑（都是实测踩出来的）

| 现象 | 原因 | 处理 |
|---|---|---|
| 登录成功但后续全 401 | 登录只返回 refresh cookie（Path=/api/user/auth），不是会话 cookie | 必须先 `auth/refresh` 换 access token |
| refresh 403 `AUTH_ORIGIN_FORBIDDEN` | 缺 `Origin` 头 | 带上 `Origin: https://api.miaotoken.cn` |
| 第二次查询 401 `AUTH_SESSION_REVOKED` | refresh cookie 单次有效，旧的已作废 | 刷新后立刻写回新 cookie |
| 分页拉回的数据有重复 | **`p` 是 1-based，`p=0` 与 `p=1` 返回同一页** | 从 `p=1` 开始，并按 `id` 去重兜底 |
| `/api/data/self` 跨度受限 | 超过 1 个月报「时间跨度不能超过 1 个月」 | 查询窗口 ≤30 天 |
| 反复登录被拒 | 登录接口限流，`retry-after: 90` | 只在 refresh 失效时才登录 |

分页修正后的对账：11-20 当天日志合计 **4.3100 美元**，与 `/api/data/self` 官方聚合的
**4.3100 美元**完全一致。

## 六、展示格式（与麦块云同构）

```
妙词元额度 · KillerJmc（killerjmc@163.com）

💰 额度（default 分组）

- 已用 26.36 美元 · 剩余 3.64 美元 · 总量 30.00 美元
- 今日消耗 0.00 美元 · 近 3 天消耗 0.06 美元

💳 账户

- 令牌 Codex（不限额度）
- 累计请求 1789 次
```

只有单一额度池，所以没有麦块云的「🎁 免费额度」块。三槽位顺序、今日/近 3 天行的位置、
账户区的列表形态都与麦块云一致。

## 七、自测记录（2026-11-25）

| 命令 | 结果 |
|---|---|
| `py_compile temp/mt_quota.py` | 通过 |
| 缺配置运行 | rc=4，提示「缺少配置文件」 |
| `--login`（正确凭证） | rc=0，落盘 refresh cookie + user_id，**配置里无 password 字段** |
| 正常查询 | rc=0，输出与麦克云同构 |
| 连续跑两次 | 输出一致（幂等）；refresh cookie 每次轮换并写回 |
| 伪造失效 cookie | rc=3，提示「登录态失效，需要重新登录」 |
| `--json` | 结构完整，含 `quota` / `usage` / `tokens` |
| 分页对账 | 392 条全量，4.3100 美元，与官方 `/api/data/self` 一致 |

## 八、待决定

- 是否写进 `quota-usage` 技能（作为第四个平台）
- 若写：需要 `scripts/miaotoken/` + `references/miaotoken-api.md` + `references/miaotoken-relogin.md`，
  并在 `route.py` 的 `PROVIDER_MAP` 加 `miaotoken.cn`、`PLATFORMS` 加条目
- 注意：`api.miaotoken.cn` 提供商的 base URL，Minis 里如果配的是它，就能自动识别