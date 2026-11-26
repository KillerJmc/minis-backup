# 命令、退出码与输出结构

入口只有一个：`scripts/route.py`。所有动作都是它的子命令。

## 用法总表

```sh
python3 scripts/route.py                 # 查当前会话所用平台的额度
python3 scripts/route.py quota           # 同上，显式写法
python3 scripts/route.py checkin         # 查额度 + 签到
python3 scripts/route.py list            # 列出支持的平台与登录态状态
```

### 全局参数

| 参数 | 作用 | 适用子命令 |
|---|---|---|
| `--json` | 输出机器可读 JSON | 全部 |
| `--provider <名>` | 指定平台，绕过自动识别 | `quota` / `checkin` |
| `--all` | 对所有平台执行 | `quota` / `checkin` |
| `--no-exchange` | 签到后不自动兑换鱼币（仅麦块云） | `checkin` |

`--provider` 与 `--all` 互斥；同时给出时以 `--provider` 为准。

平台名宽松匹配，大小写与中英文都认：

| 平台 | 标识 | 别名 |
|---|---|---|
| 麦块云 | `minekuai` | `mk`、`maikuai`、`麦块`、`麦块云` |
| 妙词元 | `miaotoken` | `mt`、`妙词`、`妙词元`、`miaoci` |
| 魔搭 | `modelscope` | `ms`、`moda`、`魔搭`、`魔塔` |
| 七牛 | `qiniu` | `qn`、`七牛`、`七牛云`、`qnaigc`、`conatus` |

未知子命令、未知参数、无法匹配的平台名一律报错退出（rc=2 / rc=1），

**不会**把 `--foo` 当成平台名或文件名继续执行。

## 退出码

单个平台：

| 码 | 含义 | 处理 |
|---|---|---|
| 0 | 正常 | — |
| 1 | 未识别供应商 / 无对应实现 / 网络错误 | 用 `--provider` 指定，或检查网络 |
| 2 | 需人工介入（业务失败、额度未到账、已签到未兑换） | 读输出里的原因 |
| 3 | 登录态失效 | 读该平台 `references/<平台>-relogin.md` 重新登录 |
| 4 | 配置缺失 | 按输出提示先登录一次 |
| 5 | 触发站点限流（妙词元登录/刷新过密） | 等 90 秒后重试，日常查询不会触发 |

`--all` 时取最严重的一个，顺序 `3 > 4 > 2 > 1 > 0`；单个平台失败不中断其余。

## `--json` 结构

顶层：

```json
{
  "ok": true,
  "exit_code": 0,
  "mode": "quota",              // quota | checkin
  "provider": {
    "label": "Minekuai-Paid",
    "base_url": "https://ai-api.minekuai.cn",
    "model": "deepseek-v4.1-flash-1017",
    "source": "group"           // group | entry | raw | group(missing) | null
  },
  "platforms": [
    {
      "platform": "minekuai",
      "platform_name": "麦块云",
      "exit_code": 0,
      "result": { }             // 平台脚本自己的 JSON，见下
    }
  ]
}
```

平台结果（`result`）各自定义：

| 平台 | 顶层字段 |
|---|---|
| minekuai | `checked_at` / `user` / `tokens` / `cash` / `coins` / `checkin` / `exchange` / `usage` / `paid` |
| miaotoken | `checked_at` / `user` / `cash` / `tokens` / `baseline` / `remain_tokens` / `keys` |
| modelscope | `checked_at` / `user` / `magicubes` / `cost` / `checkin` |
| qiniu | `checked_at` / `account` / `quota` / `stats` / `checkin` |

`list --json` 的结构不同：`{ok, current_provider, platforms[]}`，
每项含 `platform` / `name` / `aliases` / `domains` / `site` / `console` /
`login` / `implemented` / `configured` / `is_current`。

## 供应商识别链路

```
minis-config get session.primaryModel   →  "group:<uuid>" | "entry:<providerUUID>/<model>"
minis-config get groups                 →  entries[] 里第一条是回退链主力
minis-config get providers              →  customBaseURL / label
```

平台判定只看 **customBaseURL 域名**（label 用户可改）：

| 域名 | 平台 |
|---|---|
| `minekuai.cn` | minekuai |
| `modelscope.cn`、`api-inference.modelscope.cn` | modelscope |
| `qnaigc.com`、`portal.qiniu.com` | qiniu |

`minis-config get groups|providers` 返回的 `value` 是 **JSON 字符串**，需二次 `json.loads`。

## 配置与登录态

账号只从环境变量读，配置文件仅存登录态，权限 0600。

| 平台 | 配置文件 | 账号变量 | 登录方式 |
|---|---|---|---|
| minekuai | `/var/minis/shared/quota/minekuai.json` | `QUOTA_MINEKUAI_CRED`（手机号） | `scripts/minekuai/login.py`（发码后填验证码） |
| miaotoken | `/var/minis/shared/quota/miaotoken.json` | `QUOTA_MIAOTOKEN_CRED`（账号；密码） | `scripts/miaotoken/quota.py --login` |
| modelscope | `/var/minis/shared/quota/modelscope.json` | `QUOTA_MODELSCOPE_CRED`（手机号） | 浏览器，见 `references/modelscope-relogin.md` |
| qiniu | `/var/minis/shared/quota/qiniu.json` | `QUOTA_QINIU_CRED`（账号；密码） | 浏览器或 `login.py`，见 `references/qiniu-relogin.md` |

变量值格式：`账号<分隔符>密码`，分隔符可用**英文分号、中文分号、空格**；
短信验证码类平台只填手机号。解析见 `scripts/credentials.py`。

配置可用环境变量覆盖：`MK_CONFIG` / `MT_CONFIG` / `MSC_CONFIG` / `QN_CONFIG`（测试用）。

## 直接调用平台脚本（调试用）

路由脚本只是转发，平台脚本可单独跑：

```sh
python3 scripts/minekuai/quota.py [--json]
python3 scripts/minekuai/checkin.py [--json] [--status] [--no-exchange]
python3 scripts/minekuai/exchange.py [--dry-run] [--json]
python3 scripts/minekuai/login.py --phone <号> [--send-only | --code <码> | --token <token>]
python3 scripts/modelscope/quota.py [--json] [--cost]
python3 scripts/modelscope/checkin.py [--json] [--force] [--quiet]
python3 scripts/qiniu/quota.py [--json]
python3 scripts/qiniu/checkin.py [--json]
python3 scripts/qiniu/login.py [--from-env FILE | --value X] [--check]
```

退出码与上表一致。

## 已知限制

- **麦块云 token 7 天过期**，到期 rc=3，需重跑 `login.py`。
- **魔搭只能浏览器登录**：阿里 baxia 风控拦全部离线方案，已实测穷尽。
- **七牛活动额度到 2026-11-30**，之后该免费模型可能下架。
- **魔搭每次调用固定 2 魔粒**（旗舰档），额度消耗与轮次成正比。
- **麦块云免费额度已关闭**（2026-11-21 起），日常消耗走付费按量通道。
- **统计口径**：`/app/llm/requests/daily` 忽略 `groupCode` 参数，不能按通道过滤；
  按通道拆分须用 `/app/llm/requests` 明细（分页参数是 `pageNum` + `pageSize`）。
- `--all` 会依次访问多个平台，耗时可达 1 分钟以上，不要在高频路径上使用。