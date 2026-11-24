# minis-git-backup 技能：做过什么

一句话定位：把 Minis 挂载目录（含各工程的 `.git`）备份到 GitHub，并能从远程取回还原。本文件记录设计决定，接手的人不用翻会话；眼下进度看 `PROGRESS.md`。

## 功能点（用户能主动触发的事）

| 功能 | 触发关键字 | 作用 |
|---|---|---|
| 备份初始化 | 初始化备份、建备份仓库 | 在挂载根建本地 git 仓库与忽略规则（纯本地，不联网） |
| 远程配置 | 配远程、绑定仓库、换地址 | 设置 GitHub 地址并验证可达 |
| 备份提交 | 提交备份、备份一下、推上去 | 脱敏 → `.git` 改名 → 提交 → 推送 → 回验 → 改回 |
| 备份下载 | 下载备份、拉回来、还原 | 克隆到临时目录 → 原件移入 `bak/` → 备份铺回根目录 |

## 关键决定

- **`.git` 不可跟踪，但可以改名**：GitHub 拒绝 `.git` 路径，`git add -f x/.git/y` 会被静默跳过（`ls-files` 里根本不存在），真嵌套仓库直接报 `does not have a commit checked out`。v1.x 因此打成 tar.gz；v2.0.0 改为「备份时把 `.git` 临时改名 `.git-backup`」，git 就当普通目录收录，推送后在 `finally` 里改回。理由：包是快照不是增量，改一个字节就要重存整份历史（确定性打包只解决了「没改也重存」，解决不了这个）。详见 `docs/git-backup-rename-design.md`。
- **子目录 `.gitignore` 也必须改名**：它会被备份仓库自己读走。`projects/skill-generator/.gitignore` 里的 `/skill-generator/` 会把内层嵌套仓库整个静默排除（第一版自测内层 0 文件入库）。改名成 `.gitignore-backup` 后 8 个仓库全部入库。根 `.gitignore` 保留原名，它管的是备份仓库自己。
- **覆盖所有 `.git`，不去重**：用户明确要求「压缩要覆盖所有 `.git` 文件夹」。任意层级、含嵌套都处理，不限定 `projects/`。
- **推送后必须回验，且以本地为基准**：克隆远程到 `/tmp`，还原 `.git-backup`，逐文件比对。远程缺文件或内容不同 → 失败；远程多出的旧文件 → 只提示。方向写反过（拿克隆内容当基准），结果「本地新增、远程没推」检不出来。详见 `docs/git-backup-rename-design.md`。
- **中断残留要自愈**：上次执行到一半留下的 `.git-backup` 由 `heal_leftover()` 在开头改回，不改名就接着干活会把正常仓库当单元处理。
- **改名全程包在 `try/finally`**：改名期间工作区不完整，任何异常路径都必须恢复原名，否则用户看到的是一个「没有 .git」的目录。
- **临时目录用系统 /tmp**：克隆内容放在 `tempfile.mkdtemp()`，用完即删；备份不落在挂载盘里。
- **`BACKUP_GIT_NO_NETWORK=1`**：置位后拒绝任何 `https://` 的推送与还原，测试与演练只能用 `file://` 或本地路径，防止测试碰到用户真实仓库。
- **初始化只做本地**：用户明确要求「备份初始化只初始化本地，而不是 remote」。`init` 不联网、不读 token、不配远程；远程拆成独立子命令 `remote --url`。
- **仓库根 = 挂载根**：用户明确要求挂载文件夹根目录当仓库根。代价是 `restore/` 会落在仓库内部，因此 `.gitignore` 必须忽略它，否则还原出来的东西会被下次提交当成普通文件带上去。
- **还原是自动的，靠 `bak/` 兜底**：先把根目录所有条目（含 `.git`、隐藏文件）移进 `bak/<时间戳>/`，再把备份铺回来。这样既实现了"还原"又不会丢任何文件，同名冲突也自然消解。第一版是"克隆到 `restore/` 让用户自己搬"，被否掉。
- **克隆的 `.git` 必须铺回**：曾误以为要删掉克隆目录的 `.git`，结果还原后根目录不是仓库、没法继续备份。现在保留它，还原完直接可 `git log` / `backup`。
- **临时目录用系统 /tmp**：克隆内容放在 `tempfile.mkdtemp()`，用完即删；备份包不落在挂载盘里。
- **`bak/` 永不覆盖**：目录名用可读时间戳 `2026-11-24 14-40`，同一分钟多次还原追加 `(2)`，原件一律保留到用户自己清理。
- **`bak/` 不备份**：它是还原前的原件，内容与备份重复且会随每次还原翻倍，明确排除在备份之外。
- **备份跳过 `bak/`**：否则每还原一次，下一次备份就会把整份历史原件再存一遍。
- **只保留两个环境变量**：`BACKUP_GIT_TOKEN` 与 `BACKUP_GIT_REPO`（`作者名/仓库名`）。第一版有 3 个（含 `GIT_AUTHOR_*`），被否掉——备份提交统一署名 `Minis Agent` 就够，作者变量是噪音。
- **`BACKUP_GIT_REPO` 一箭三雕**：拼仓库地址、校验推送目标（防止把备份推到别人的仓库）、还原兜底。比单独存 remote URL 更可靠，因为环境变量不会随目录被替换而失效。
- **推送前必须核对远端**：先把远程 `clone --bare` 到临时目录比对历史。远端领先或分叉一律终止，绝不 force push——备份仓库最怕的就是用旧内容盖掉新备份。
- **变量名统一 `BACKUP_GIT_` 前缀**：`BACKUP_GIT_TOKEN` / `BACKUP_GIT_REPO`，与本技能名对应，一眼能看出属于哪个备份任务。缺变量时给预填链接，不让用户猜。
- **禁止任何回滚远端的操作**：不使用 `git push --force`、不使用 `reset --hard`，测试里移动分支指针也只用 `update-ref`（不碰工作区）。备份仓库的价值全在历史，回滚远端等于销毁备份。
- **还原前必须先看本地有没有 `.git`**：有仓库走 `bak/` 保护流程；没有且目录为空就直接整份铺入（没东西可丢，不必造 `bak/`）；没有但目录非空则停下报 rc=6 让用户决定。三种情况覆盖了「换设备」「误删」「目录里已有别的东西」。
- **推送前用 fetch 而不是 clone**：`git fetch <url> <refspec>` 把远程写进本地跟踪分支，判断祖先关系即可，不需要临时目录，也不用清理。远程还没有该分支时按空仓库处理。
- **挂载根仓库同样受 Angular 规范约束**：类型固定 `chore`、范围固定 `backup`，标题 ≤50 字只报类别与数量，明细放正文。理由：备份仓库的历史会被人工翻阅，一句 `备份 5 个 skill` 比一长串路径可读；历史提交也按此改写，不保留旧格式。
- **提交信息按实际变动生成**：从 `git status --porcelain` 读状态位（`A` 即新增），分出「新增 skill / 新增工程 / 更新 skill / 更新工程 / memory / 其他」；skill 与否按 `projects/<名>/` 下有无 `SKILL.md` 判断，不靠名字猜。`.gitignore`、`.gitkeep` 是标记文件，不计入，否则每条提交都会出现噪音。

## 目录

```
projects/minis-git-backup/            工程层（工程仓库）
├── PROJECT.md                        本文件：为什么这样设计
├── PROGRESS.md                       现在到哪、下一步
├── .gitignore                        排除技能目录与大文件（temp/ 例外）
├── temp/                             设计稿、实测记录（入库）
├── docs/                             调研与设计文档
│   ├── github-credentials-design.md  推送变量、token 权限、安全边界
│   └── git-backup-rename-design.md   v2 改名机制：为什么放弃 tar.gz、ignore 改名、回验方向
└── minis-git-backup/                 技能层（技能仓库）
    ├── SKILL.md                      功能表 + 五个功能 + 执行约束
    ├── CHANGELOG.md                  变更记录
    ├── references/commands.md        参数、退出码、已知限制
    ├── scripts/backup.py             唯一入口：init / remote / backup / scan / restore
    ├── scripts/privacy.py            敏感信息扫描与脱敏
    ├── tests/{cases.json,run.py,README.md}
    └── .gitignore
```

工程层不放 `WORKFLOW.md` 与 `deploy.py`：流程见技能生成器 `references/git-workflow.md`，部署用 `python3 /var/minis/skills/skill-generator/scripts/deploy.py`。`assets/` 暂不需要，未创建。

## 上线链路

工作副本 `projects/minis-git-backup/minis-git-backup/` → `/var/minis/skills/minis-git-backup/` → `ws.py sync --push` → `/var/minis/mounts/Minis/skills/minis-git-backup/` → `skills-dist/minis-git-backup_v<版本>.zip`

部署用共享脚本，工程里不放副本：

```sh
cd "/var/minis/mounts/Minis/projects/minis-git-backup"
python3 /var/minis/skills/skill-generator/scripts/deploy.py
```

## 遗留

- 增量由 git 自己做（改一个文件只增该文件的对象），但 `.git/objects` 里的历史对象无法瘦身，仓库只增不减；真要压体积得 `git gc`/重写历史。
- 回验要完整克隆一份到 `/tmp`，大仓库时比较慢；目前没有 `--no-verify` 跳过开关。
- 不自动建 GitHub 仓库、不解决推送冲突。
- `bak/` 只由用户手动清理，脚本不会自动删除任何原件。
