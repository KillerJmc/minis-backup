# 魔搭（ModelScope）运行时速查

> 只放脚本运行时需要查的参数与字段。完整调研（baxia 风控判定、签到机制推导、踩坑）
> 在工程层 `docs/modelscope-api-research.md`，不随技能发布。

站点：`https://modelscope.cn` ｜ 额度页：`https://modelscope.cn/magicube/usage`
配置：`/var/minis/shared/msc-quota/config.json`（`MSC_CONFIG` 可覆盖，0600）
登录：**必须走浏览器**，流程见 [`modelscope-relogin.md`](modelscope-relogin.md)

## 关键接口

只认 Cookie `m_session_id`，Bearer 无效。`api_get()` 已剥掉 `{success, request_id, data}` 外层。

| 用途 | 路径 | 主要字段 |
|---|---|---|
| 余额 | `GET /openapi/v1/magicubes/balance` | `balance` / `expiring` |
| 明细 | `GET /openapi/v1/magicubes/transactions` | `type`、`change`、`created_at` |
| 发放规则 | `GET /openapi/v1/magicubes/earn/rules` | `category_key`、`today_used`、`today_remain` |

`transactions` 的 `type` 取值：`SPEND_CONFIRM`、`EXPIRE`、`EARN`；分页用 `page` + `page_size`。

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