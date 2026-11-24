# 调研脚本

调研过程的留档，用来**复现结论**。不是技能的一部分，不参与部署。
结论已沉淀到 `docs/*-research*.md`，这里保留的是能重跑出那些数字的脚本。

## minekuai/usage_daily.py

按天 + 按 `groupCode` 聚合调用明细的消耗量。

复现的结论：永久池消耗全部标为 `lite_token`；今日池（`default`）在关闭兑换后没有记录；
`paygo` 明细加总与 `paid.totalUsed` 差约 1–3%。

关键点：`/app/llm/requests` 的分页参数是 **`pageNum` + `pageSize`**。
传 `page` / `current` / `offset` 会被静默忽略，永远返回第一页——
曾因此把同一页累加 29 次得出假结论，详见 `docs/minekuai-research-log.md`。

## minekuai/usage_by_channel.py

同时打印三个额度池（today / permanent / paid）的快照，用于核对「谁在扣账」。

复现的结论：50 秒对话期间只有 `paid.totalUsed` 增长，两个免费计数纹丝不动。

## minekuai/probes/

调研期间逐轮写的探测脚本，按时间顺序。**不要当工具用**，它们只回答当时的问题：

| 文件 | 当时要验证什么 |
|---|---|
| `probe_mk.py` / `probe_mk2.py` | 有哪些 `/app/*` 路径存在 |
| `probe3.py` ~ `probe6.py` | 购买记录、售卖开关、附加包、通道过滤参数 |
| `probe7.py` ~ `probe10.py` | 分页行为与 `groupCode` 分布（含假结论复现） |
| `probe11.py` / `probe12.py` | 14 天窗口、API Key 字段 |
| `agg*.py` | 按天 / 按通道聚合 |
| `chk*.py` | 分页参数名对比、上限字段核对 |
| `dump*.py` | 原始响应全量转储 |

## 运行

都直接读 `/var/minis/shared/mk-quota/config.json` 里的 token，均需联网，输出不写盘：

```sh
python3 temp/research/minekuai/usage_daily.py
python3 temp/research/minekuai/usage_by_channel.py
```