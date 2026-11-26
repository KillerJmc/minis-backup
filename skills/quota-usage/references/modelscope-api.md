# 魔搭（ModelScope）运行时速查

> 只放脚本运行时需要查的参数与字段。完整调研（baxia 风控判定、签到机制推导、踩坑）
> 在工程层 `docs/modelscope-api-research.md`，不随技能发布。

站点：`https://modelscope.cn` ｜ 额度页：`https://modelscope.cn/magicube/usage`
配置：`/var/minis/shared/quota/modelscope.json`（`MSC_CONFIG` 可覆盖，0600）
登录：**必须走浏览器**，流程见 [`modelscope-relogin.md`](modelscope-relogin.md)

## 关键接口

只认 Cookie `m_session_id`，Bearer 无效。`api_get()` 已剥掉 `{success, request_id, data}` 外层。

| 用途 | 路径 | 主要字段 |
|---|---|---|
| 余额 | `GET /openapi/v1/magicubes/balance` | `balance` / `expiring` |
| 明细 | `GET /openapi/v1/magicubes/transactions` | `type`、`change`、`created_at` |
| 发放规则 | `GET /openapi/v1/magicubes/earn/rules` | `category_key`、`today_used`、`today_remain` |

`transactions` 的 `type` 取值：`SPEND_CONFIRM`、`EXPIRE`、`EARN`；分页用 `page` + `page_size`。

## 签到触发（两级，全自动）

魔搭的每日发放不是调接口拿的，而是「当天首次带登录态的**前端**访问」由服务端判定。
纯 HTTP 只能拿到 4519 字节的 SPA 空壳，服务端不认，所以必须分两级：

| 级别 | 做法 | 成功率 |
|---|---|---|
| 一级 | 纯 HTTP GET `/home` 带 `m_session_id` | 有时不生效 |
| 二级 | `minis-browser-use new_tab` 打开 `https://modelscope.cn/my/overview`，让前端 JS 跑起来 | 实测有效 |

`checkin.py` 已内置两级：一级失败自动走二级，**不需要用户操作**。
判断依据：`earn/rules` 里 `category_key=daily` 的规则 `today_remain > 0`。

**坑**：
- 浏览器标签页上限 3 个，到顶时 `new_tab` 报 `Maximum of 3 tabs reached`；
  脚本会先 `close_tab` 再重开
- 刚换 cookie 后第一次签到必走二级：`passport.modelscope.cn` 的会话在主域还没生效
- 二级完成后等约 8 秒再读 `earn/rules`，入账有延迟

## 输出结构

```
魔搭额度

💰 魔粒额度

- 已用 A · 剩余 B · 总量 C
- 今日消耗 D · 近 3 天消耗 E

💳 账户

- 签到：是/否
- 今日调用 N 次 ｜ 近 3 天 M 次
```

- **总量与已用都排除「过期回收」**（`EXPIRE` 流水不计入任何一边），两者相加才与剩余闭合
- 只有 `SPEND_CONFIRM` 计入已用；`earn/rules` 里 `category_key=daily` 的规则今日是否领取决定「签到」
- 平台按次计费（旗舰档 2 魔粒/次），**接口不提供 token 数**，无法折算 token

## 额度口径

- 每日发放 **200 粒**（注册并登录）+ **50 粒**（绑定阿里云），**都只有 1 天有效期**，隔天清零
- 没有签到按钮、没有签到接口；机制是「当天首次带登录态访问站点时服务端发放」
- 判断今天是否已领：看 `earn/rules` 里两条 `daily` 规则的 `today_remain`，为 0 即已领
- 旗舰档模型 **2 魔粒/次调用**

## 退出码

`0` 正常 ｜ `1` 网络/接口错误 ｜ `2` 需人工介入（今日额度未到账）｜
`3` 登录态失效 ｜ `4` 配置缺失

## 已知限制

- 登录只能浏览器，自动化程度受限；`m_session_id` 失效后必须人工重登
- 刚重登后接口可能短暂返回余额 0，稍等再查，不是真的没额度
- `checkin.py` 的 `--force` 会在已领取时也再触发一次首页（幂等，用于确认）