# quota-usage 技能：做过什么

一句话定位：用户说「查额度 / 签到 / 有哪些平台」时，按当前会话绑定的供应商自动查对应平台的额度。
本文件记录设计决定，接手的人不用翻会话；眼下进度看 `PROGRESS.md`。

## 功能点（用户能主动触发的事）

| 功能 | 触发关键字 | 作用 |
|---|---|---|
| 额度查询 | 查额度、还剩多少、消耗了多少 | 按当前会话的供应商查余额与消耗 |
| 每日签到 | 签到、每日签到、领额度 | 领当日额度，麦块云签到后自动兑换 |
| 平台列表 | 支持哪些平台、查所有平台 | 列出平台、别名、登录态状态 |

## 关键决定

- **按域名认平台，不看 provider 名字**：`label` 用户可改（实测被叫过 `Minekuai`、`Minekuai-Paid`），
  域名不会变。所以读 `customBaseURL` 的域名匹配。
- **默认只查当前平台，不主动 `--all`**：三个平台各有独立登录态与额度，用户问「我的额度」时
  查的就是当前在用的那个；`--all` 只在用户明确点名多个平台时才用。
- **付费额度排在免费额度之前**：2026-11-21 麦块云关闭免费不限量后，付费按量才是真实可用额度。
  曾经把「合计可用 = 今日 + 永久」放在最上面，结果把不可用的额度也算了进去，会误导。
- **签到与兑换合并成一步**：账户的 auto 模式不是实时兑换，鱼币会一直躺着。
  曾经需要签到后再手动跑 `exchange.py`，现在 `checkin` 直接包含兑换，避免「额度没涨」的困惑。
- **额度数值不写进测试断言**：服务端状态每分钟在变（对话本身在消耗），
  把具体数字写进期望，测试几分钟后就自然失效。只断言结构与契约。
- **入口子命令化而不是 flag 式**：`--checkin` / `--list` 混在一个命令里时，参数组合爆炸，
  且 `--foo` 有被当成平台名的风险。改成 `quota` / `checkin` / `list` 三个子命令，未知子命令直接 rc=2。
- **各平台脚本放 `scripts/<平台>/`**：三家的 `quota.py` 同名，用子目录隔离就不用加前缀，
  脚本内部那句 `from quota import ...` 可以原样保留。

## 目录

```
projects/quota-usage/            ← 工程层（工程仓库）
├── PROJECT.md                   本文件：设计决定
├── PROGRESS.md                  当前状态与待办
├── .gitignore                   排除技能目录，temp/ 例外入库
├── temp/                        调研中间稿、可复现结论的探测脚本
├── docs/                        沉淀下来的调研结论（见下）
└── quota-usage/                 ← 技能层（独立 git 仓库）
    ├── SKILL.md                 功能表 + 各功能用法 + 执行约束
    ├── CHANGELOG.md             每个版本改了什么
    ├── references/              运行时速查（命令、退出码、各平台参数）
    ├── scripts/route.py         唯一入口，子命令 quota/checkin/list
    ├── scripts/<平台>/          各平台脚本，同名 quota.py 用子目录隔离
    └── tests/                   cases.json + run.py + README.md
```

工程层不放 `WORKFLOW.md` 与 `deploy.py`：上线工具只有一份，在
`/var/minis/skills/skill-generator/scripts/` 下，所有工程共用。

## docs/

- [`docs/minekuai-api-research.md`](docs/minekuai-api-research.md) — 麦块云接口调研：
  四层额度体系、50+ 接口清单、`groupCode` 通道归属实测、踩坑与待验证。
- [`docs/minekuai-research-log.md`](docs/minekuai-research-log.md) — 麦块云付费额度调研**过程**：
  四轮探测顺序、18 条多余猜测、分页参数名错误导致的假结论如何翻案、三通道独立计数的实测。
- [`docs/modelscope-api-research.md`](docs/modelscope-api-research.md) — 魔搭接口调研：
  阿里 baxia 风控判定、「签到」实为访问触发的发放机制、计费档位。
- [`docs/qiniu-api-research.md`](docs/qiniu-api-research.md) — 七牛接口调研：
  单 Cookie 鉴权、活动额度与真实消耗的口径差异（K token）。

调研**过程**（可复现结论的脚本）不入 `docs/`，放在 `temp/research/`，
用 `chore(temp):` 单独提交，与代码提交分开。

## 上线链路

发布统一走 `release.py`，两轮之间由 snapshot 哈希守着：

```
quota-usage/ 工作副本（技能仓库，唯一可改）
   ↓ python3 /var/minis/skills/skill-generator/scripts/release.py prepare quota-usage
      输出变更记录条目 + 文件清单 + 增删行数 + snapshot（写入 temp/.release-pending.json）
   ↓ 把这段贴给用户，等明确点头
   ↓ python3 .../release.py confirm <snapshot>
      1. 重算 snapshot，与传入值不一致 → 拒绝（rc=3），要重新 prepare
      2. validate.py --allow-dirty（发布阶段工作区必然脏）
      3. tests/run.py，末行不是「失败 0 项」→ 拒绝
      4. commit 技能仓库（release(quota-usage): v<版本>）
      5. deploy.py：校验 → 测试 → 镜像式同步 → ws.py sync --push → 打包归档
      6. commit 工程仓库（docs(progress): 记录 v<版本> 上线）
```

底下的 `deploy.py` 单独也能用，行为同上第 5 步；`--dry` 只打印差异，`--pack-only` 只出包不上线。
打包源取挂载镜像，顺序是「写 `.zip.tmp` → 校验非空 → 原子改名 → 成功后才挪旧版」。

三处必须一致：工作副本、`/var/minis/skills/`、外部镜像。两者都不该出现 `.git`、`.gitignore`、`.pyc`。
`deploy.py` 的 `SKIP` 会把 `__pycache__` 从两侧都滤掉，所以**它不会清理产物里已存在的 `.pyc`**——
产物脏了要单独清。

## 遗留

- 无