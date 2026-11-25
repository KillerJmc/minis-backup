---
name: minis-git-backup
description: 备份初始化，远程配置，备份提交，隐私检查，备份下载
version: 2.1.0
triggers: 初始化备份,配置远程,提交备份,检查隐私,下载备份
---

备份初始化，远程配置，备份提交，隐私检查，备份下载。

## 功能

| 功能 | 触发关键字 | 作用 |
|---|---|---|
| 备份初始化 | 初始化备份、建备份仓库 | 在挂载根建本地 git 仓库与忽略规则（纯本地，不联网） |
| 远程配置 | 配远程、绑定仓库、换地址 | 设置 GitHub 地址并验证可达性 |
| 备份提交 | 提交备份、备份一下、推上去 | 脱敏 → `.git` 改名 → 提交 → 推送 → 回验 → 改回 |
| 隐私检查 | 检查隐私、扫一下隐私 | 扫描 memory 的敏感信息，按规则打码 |
| 备份下载 | 下载备份、拉回来、还原 | 克隆到临时目录 → 原件移入 `bak/` → 备份铺回根目录 |

包名、参数、退出码、已知限制见 [`references/commands.md`](references/commands.md)。

**备份的是什么**：`/var/minis/mounts/Minis/` 整个目录，除 `bak/`、可重建缓存与**隐私记忆**之外**全部逐文件入库**。

**隐私记忆不上传**：`memory/` 下的日期文件（`YYYY-MM-DD.md`）记录的是每天的工作细节，含隐私，**不备份、不上传**。`GLOBAL.md`、`SOUL.md` 这类配置照常备份。过滤由 `.gitignore` 规则与回验基准共同保证，不靠人工记得删。

**怎么处理 `.git`**：git 拒绝跟踪任何 `.git` 路径（`git add -f x/.git/y` 会报 `is in submodule`）。所以备份时把**所有** `.git`（任意层级、含嵌套）临时改名成 `.git-backup`，git 就能当普通文件跟踪；提交推送后立刻改回原名。

子目录的 `.gitignore` 同样改名成 `.gitignore-backup`——它的规则会作用于备份仓库，实测 `projects/a/.gitignore` 里的 `/*/` 能把内层嵌套仓库整个静默排除，不改名就等于没备份内层。

这样做的结果：

- 远程 GitHub 上能像浏览普通仓库一样打开每个文件夹、每个文件（`.git-backup` 里是二进制对象，看不了但不影响其他文件）
- 子仓库的 objects 按对象去重，改一个文件只增该文件大小的对象，不会整包重来
- 还原后子仓库可直接 `git log`、`git commit`、`git push`

`.gitignore` 由脚本生成，只排除 `bak/`、缓存与 `memory/` 下的日期记忆。

## 备份初始化

**何时用**：第一次在这台设备上给挂载目录建备份仓库。**纯本地操作，不联网、不配远程、不需要 token。**

```sh
python3 /var/minis/skills/minis-git-backup/scripts/backup.py init
```

做两件事：写 `.gitignore`（只排除 `bak/` 与可重建缓存，其余全部入库）、`git init`。**不建任何归档目录**——v1 的 `.archives/`、`.git-archive/` 都已废弃。

| 输出 | 含义 |
|---|---|
| `已创建：.gitignore, .git/` | 本次新建了什么 |
| `仓库已存在：<路径>` | 之前初始化过，继续补缺失项 |
| `将更新 .gitignore` | `--dry` 预演：规则与本版不一致，正式执行会改写 |
| `.gitignore 已是正确内容` | 无需改动 |

`--dry` 只打印将做的动作，结尾明说「未写入」。

## 远程配置

**何时用**：建好 GitHub 空仓库后绑定地址，或换一个仓库。

```sh
python3 /var/minis/skills/minis-git-backup/scripts/backup.py remote --url https://github.com/<用户名>/<仓库>.git
python3 /var/minis/skills/minis-git-backup/scripts/backup.py remote --show
```

`--show` 只打印当前 `origin`；设置时会顺带用 `BACKUP_GIT_TOKEN` 跑一次 `ls-remote` 验证，没设 token 时只提示不报错。

| 输出 | 含义 |
|---|---|
| `已设置 origin = …` | 地址已写入本地仓库 |
| `远程可访问：…` | token 有效、仓库存在 |
| `远程无法访问：…` | 地址错或 token 无效，先修再提交 |
| `未设置 BACKUP_GIT_TOKEN，推送时会被拒绝` | 地址已存，token 待补 |

## 备份提交

**何时用**：想把当前挂载目录（含各子仓库的 git 历史）存到 GitHub。

```sh
python3 /var/minis/skills/minis-git-backup/scripts/backup.py backup
```

做的事：

1. **隐私脱敏**：扫描 `memory/` 下的 Markdown，命中项就地打码，不询问、不中断（日期记忆本身不上传，扫描只针对会入库的 `GLOBAL.md` 等）；
2. 把所有 `.git` 改名成 `.git-backup`、子目录的 `.gitignore` 改名成 `.gitignore-backup`；
3. `git add -A` → 按实际变动生成 Angular 提交信息 → `commit`；
4. 推送前用 `git fetch` 取回远程比对历史：远端领先或分叉立即终止；
5. `push`；
6. **回验**：克隆远程到 `/tmp`，还原 `.git-backup`，**以本地为基准**逐文件比对——远程缺文件或内容不同即判定推送失败（远程多出的旧文件只提示）；
7. **无论成败都改名回来**（`finally` 保证），异常中断也不会留下 `.git-backup`。

提交信息示例：

```
chore(backup): 备份 8 个仓库、176 个文件

`工程仓库`：projects/minis-git-backup、projects/quota-usage 等
`文件`：memory 7 个、projects 106 个、skills 53 个
```

类型固定 `chore`、范围固定 `backup`，主题 ≤50 字只报数量，明细放正文；`-m` 自定义信息要过同一套校验。

| 输出 | 含义 |
|---|---|
| `已改名 N 个 .git → .git-backup` | 改名完成，可以开始提交 |
| `已提交：chore(backup): …` | 本地提交完成 |
| `核对远端历史（master）...` | 正在 fetch 远程比对 |
| `已推送：作者/仓库/master` | 推送完成 |
| `回验通过：克隆验证通过：N 个子仓库、M 个 ignore 文件、K 个文件逐字节一致` | 远程内容确认与本地完全一致 |
| `已恢复 N 个 .git-backup → .git` | 收尾完成，本地恢复原状 |

出错怎么办：未初始化 → 先跑 `init`；缺 token → 码 5，加 `--local` 只本地提交；推送失败或**回验失败** → 远程都不可信，修好网络/token 后重跑。只看会发生什么加 `--dry`（不改名、不提交）。

## 隐私检查## 隐私检查

**何时用**：提交前想先看 memory 里有什么敏感内容；或手动清理。

**只作用于提交链路**：脱敏发生在 `backup` 提交前，`restore` 还原时**不做任何脱敏**——还原就是把备份原样放回来，改不改 memory 由用户自己决定。

```sh
python3 /var/minis/skills/minis-git-backup/scripts/backup.py scan        # 只报告
python3 /var/minis/skills/minis-git-backup/scripts/backup.py scan --fix  # 报告并打码
```

**脱敏是提交的一部分，不询问用户**：`backup` 会在提交前自动脱敏，推送完成后把清单报出来（提交信息里也带一行）。要事前知情就用 `scan` 单独跑。

打码规则——**只留首尾各一个字，中间全部星号；密码类全星号**：

| 类型 | 处理 | 例子 |
|---|---|---|
| 手机号 | 留首尾各一字符 | `1*********5` |
| 账号名 | 留首尾各一字符 | `K*******c` |
| 32 位以上十六进制串 | 留首尾各一字符 | `4******************************1` |
| 邮箱 | 留首尾各一字符 | `a******m` |
| 密码赋值 | **全星号** | `密码=*********` |
| API key / GitHub token / AWS key | **全星号** | `*********************************` |
| JWT / Bearer 令牌 / 私钥块 | **全星号** | `**************************************` |
| IPv4 地址 | 留首尾各一字符 | `1*********1` |

| 输出 | 含义 |
|---|---|
| `memory 扫描：N 处命中` | 命中总数，逐条列出文件名、行号、类型、打码片段 |
| `memory 干净，无需脱敏` | 没有命中 |
| `已脱敏 N 处（K 个文件）` | 打码已写回，文件进 git 备查 |

只改 `memory/` 下的文件；扫描结果永远不打印明文，只有打码片段。

## 备份下载

**何时用**：换设备、误删文件、想把线上备份恢复成当前状态。

```sh
python3 /var/minis/skills/minis-git-backup/scripts/backup.py restore
```

**自动还原，不丢文件**，顺序是：

1. `git clone --depth 1` 到系统临时目录（`/tmp/minis-restore-*`，用完即删）；
2. 把临时目录里所有 `.git-backup` 改成 `.git`、`.gitignore-backup` 改成 `.gitignore`；
3. 把**挂载根现有的所有条目**移进 `bak/<YYYY-MM-DD_HH-MM>/`（人类可读，下划线避免转义）——包括根目录的 `.git`、`.gitignore`、隐藏文件、`memory/`、`projects/`、`skills/`，一件不少；
4. 把临时目录的内容铺回根目录；
5. 报告 `bak/` 路径，由用户确认后自行删除。

| 输出 | 含义 |
|---|---|
| `克隆到临时目录 …` | 正在取远程 |
| `已恢复 N 个子仓库（.git-backup → .git）、M 个 .gitignore-backup → .gitignore` | 子仓库已还原 |
| `原目录 N 个条目已移入：…/bak/<时间戳>` | 旧内容已安全搬走 |
| `备份已铺回根目录：N 个条目` | 还原完成 |
| `原文件保留在 …，确认无误后可自行删除` | 收尾提示 |

**先判断本地有没有仓库**：顶层有 `.git` 走 `bak/` 保护流程；没有 `.git` 且目录为空就直接整份铺入，不建 `bak/`；没有 `.git` 但目录非空则停下（退出码 6）并列出清单，由你决定怎么处理，脚本不覆盖任何东西。

**还原后仓库立即可用**：克隆来的 `.git` 一并铺回，`git log`、`git status` 直接能读，可以接着 `backup`。若需要提交身份，`backup` 会自动补 `user.email`/`user.name`。

出错怎么办：克隆失败不会动根目录一个文件（临时目录删掉即可）。想先看会发生什么加 `--dry`。

## 执行约束

- **仓库根是挂载目录**，不是本技能的工程目录；技能自己的 `projects/minis-git-backup/` 也会被一起备份。
- **测试绝不碰真实远程**：脚本支持 `BACKUP_GIT_NO_NETWORK=1`，置位后拒绝任何 https 地址，测试只用本地裸仓库。
- **推送要两个环境变量**：`BACKUP_GIT_TOKEN`（凭据）与 `BACKUP_GIT_REPO`（`作者名/仓库名`）。都缺一不可，只读不写盘。
- **缺变量时给引导**：一次列出全部缺失项、用途，并附预填好的设置页链接，用户点开填值即可，不要让他自己猜变量名。
- **绝不 force push、绝不用 `reset --hard`**：推送前比对的临时仓库只用来读，移动本地分支指针只用 `update-ref`。备份仓库里最珍贵的是历史，任何回滚远端的操作都禁止。
- **不替用户判断**：还原铺回后不改名、不搬移、不合并；冲突已在移走原件后自然消解。
- **改动只发生在 `.git` 的名字上**：备份期间改名为 `.git-backup`，结束或异常都恢复；不删文件、不改内容。

minis_url: minis://skills/minis-git-backup/SKILL.md
