---
name: quota-usage
description: 额度查询，每日签到，平台列表
version: 1.3.2
triggers: 额度,余额,签到,每日签到,消耗,魔粒,麦块,魔搭,七牛,quota
---

额度查询，每日签到，平台列表。

## 功能

| 功能 | 触发关键字 | 作用 |
|---|---|---|
| 额度查询 | 查额度、还剩多少、消耗了多少 | 按当前会话的供应商查余额与消耗 |
| 每日签到 | 签到、每日签到、领额度 | 领当日额度，麦块云签到后自动兑换 |
| 平台列表 | 支持哪些平台、查所有平台 | 列出平台、别名、登录态状态 |

## 额度查询

**什么时候用**：用户问还剩多少、今天用了多少、额度为什么没了。不带平台名时只查当前会话在用的那一个。

**跑什么**：

```sh
python3 scripts/route.py quota
python3 scripts/route.py quota --provider 魔搭    # 指定平台，认中英文别名
python3 scripts/route.py quota --all             # 仅当用户明确说「都查」时用
```

**输出怎么读**：分三区，付费额度在前（免费不限量已关闭，付费按量是真实可用额度），
然后免费额度、账户。每个额度池都是「已用 · 剩余 · 总量」三槽位，两区排版一致便于对照；
`剩余` 是还能用的量。付费与永久额度另有一行「今日消耗 · 近 3 天消耗」，按平台调用通道统计。

示例（数字仅示意）：

```
麦块云额度 · <昵称>（<手机>）

💰 付费额度（按量付费）

- 已用 A · 剩余 B · 总量 C
- 今日消耗 D · 近 3 天消耗 E

🎁 免费额度

- 今日 已用 F · 剩余 G · 总量 H
- 永久 已用 I · 剩余 J · 总量 K
  - 今日消耗 L · 近 3 天消耗 M

💳 账户

- 鱼币 N
- 现金 ¥0.00
- 签到：是（连签 X 天）
```

额度超过 1 亿显示为「亿」，1 万以上为「万」。今日池每天清零，所以没有跨天概念；
永久池的消耗在调用明细里记为 `lite_token` 通道，今日池记为 `default`，付费记为 `paygo`。

`--json` 的结构见 [`references/commands.md`](references/commands.md)。

**出错怎么办**：`3` 登录态失效，按平台读 `references/<平台>-relogin.md` 重新登录；
`4` 还没登录过；`2` 业务侧有问题（如兑换暂停），原因在输出里；`1` 网络或未识别供应商。

## 每日签到

**什么时候用**：用户说签到、每日签到，或想领当日额度。每天一次，重复跑无副作用。

**跑什么**：

```sh
python3 scripts/route.py checkin
python3 scripts/route.py checkin --no-exchange   # 只签到，不兑换
```

**输出怎么读**：签到成功会报获得多少鱼币与连签天数；麦块云随后自动把鱼币兑换成当日额度，
所以**不要**再补一条兑换命令——兑换单位已归零，重复跑只会显示「鱼币不足」。
魔搭没有签到按钮也没有签到接口，机制是「当天首次带登录态访问站点时服务端发放」，已按此实现。

**出错怎么办**：`3` 登录态失效（魔搭必须走浏览器，见 `references/modelscope-relogin.md`）；
`2` 已签到但兑换未成功，通常是平台暂停了兑换通道，不是本地问题。

## 平台列表

**什么时候用**：用户问支持哪些平台、某个平台的登录态还在不在、当前用的是哪家。

**跑什么**：

```sh
python3 scripts/route.py list
python3 scripts/route.py list --json
```

**输出怎么读**：每个平台列出别名、域名、官网、登录方式与状态（已实现 / 未实现、已配置登录态 / 未登录），
末尾标出当前会话在用的那个。

**出错怎么办**：`1` 读不到当前会话的供应商信息（`minis-config` 无返回）。
`list` 本身不联网，能列出来就说明本地配置完好，状态显示「未登录」不代表平台不可用，只是还没存过凭证。

## 详细文档

| 内容 | 位置 |
|---|---|
| 参数、退出码、JSON 结构、已知限制 | [`references/commands.md`](references/commands.md) |
| 给新平台加实现的流程与脚本约定 | [`references/dev-workflow.md`](references/dev-workflow.md) |
| 麦块云：接口与字段速查 | [`references/minekuai-api.md`](references/minekuai-api.md) |
| 魔搭：接口速查 / 登录失效流程 | [`references/modelscope-api.md`](references/modelscope-api.md)、[`modelscope-relogin.md`](references/modelscope-relogin.md) |
| 七牛：接口速查 / 登录失效流程 | [`references/qiniu-api.md`](references/qiniu-api.md)、[`qiniu-relogin.md`](references/qiniu-relogin.md) |

## 执行约束

- **不主动用 `--all`**：三个平台各有独立登录态与额度，用户问「我的额度」时查的就是当前在用的那个。
- **平台靠域名判定**：读 `minis-config` 的 `session.primaryModel` → `groups` → `providers.customBaseURL`，
  按域名匹配平台；provider 的 label 用户可改，不作依据。
- **不要重跑兑换脚本**：`checkin` 已含兑换，重复跑只会报「鱼币不足」。
- 平台脚本可单独调用（调试用），退出码与入口一致，见 `references/commands.md`。
- 测试：`python3 tests/run.py`（离线）/ `--live`（含联网），末行须为「失败 0 项」。