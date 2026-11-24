# 测试说明

对话级回归。默认离线：不联网、不读真实登录态，只验编译、CLI 契约与错误分支。
联网用例（`network: true`）默认跳过，额度结果本身只能靠真实会话验证。

```sh
python3 tests/run.py                 # 离线全跑
python3 tests/run.py --live          # 含联网用例
python3 tests/run.py -k list         # 只跑 id 含 list 的
python3 tests/run.py --selftest      # 额外跑负向自检
```

末行须为 `共 N 项，失败 0 项`。退出码 0 全绿 / 1 有失败。

## 用例（tests/cases.json）

每条用例是「用户原话 → 命令 → 期望」，字段：

| 字段 | 含义 |
|---|---|
| `id` | 唯一标识，`-k` 按它过滤 |
| `user` | 用户会怎么说这件事（对话级视角） |
| `argv` | 传给 `scripts/route.py` 的参数 |
| `env` | 追加的环境变量（用于指向不存在的配置文件） |
| `expect_rc` | 期望退出码 |
| `stdout_has` / `stderr_has` | 输出里必须出现的片段 |
| `stdout_not_has` | 输出里不应出现的片段 |
| `idempotent` | 为真时连跑两次，要求结果完全一致 |
| `network` | 为真时默认跳过，加 `--live` 才跑 |

## 覆盖范围

| id | 验什么 |
|---|---|
| static | 全部 `.py` 编译通过（含各平台脚本） |
| list-basic | `list` 列出三个平台与当前会话标记 |
| list-json | `--json` 结构含 `platforms` / `is_current` / `implemented` / `configured` |
| list-json-idempotent | 同一命令连跑两次结果一致 |
| default-subcommand | 不带子命令时按 `quota` 处理 |
| provider-alias-cn / -en | 中英文别名（`麦块` / `ms`）都能匹配 |
| missing-config | 配置缺失 → rc=4，提示先登录 |
| unknown-subcommand | 未知子命令 → rc=2，打印用法 |
| unknown-flag | 未知参数 → rc=2，**不**当成位置参数吞掉 |
| unknown-provider | 未知平台 → rc=1，列出可用平台 |
| provider-all-mutually-exclusive | `--provider` 与 `--all` 互斥 → rc=2 |
| live-quota | 真实查询返回 `checked_at` / `tokens`（需 `--live`） |

## 负向自检

`--selftest` 会临时构造一条期望值故意写错的用例（`expect_rc: 99`），
要求执行器**报告失败**。如果它"通过"了，说明执行器本身不校验，测试全绿也毫无意义。

## 为什么不做额度数值断言

额度是服务端状态，每天变、每分钟变（对话本身就在消耗）。把具体数字写进期望，
测试会在几分钟后自然失效。所以只断言结构与契约，数值由人读输出确认。