# 参数、退出码与已知限制

## 调用

```sh
python3 <技能>/scripts/backup.py [--mount <目录>] <子命令> [选项]
```

| 全局选项 | 说明 |
|---|---|
| `--version` | 打印 `minis-git-backup 2.0.0` |
| `--mount <目录>` | 挂载根，默认 `/var/minis/mounts/Minis`；也可用环境变量 `MINIS_MOUNT` |

无子命令时打印帮助，退出码 `2`。

## 环境变量

| 变量 | 必填 | 说明 |
|---|---|---|
| `BACKUP_GIT_TOKEN` | 推送/还原时必填 | GitHub fine-grained token，Contents 读写 |
| `BACKUP_GIT_REPO` | 推送/还原时必填 | `作者名/仓库名`，用于拼地址、校验目标、还原兜底 |
| `BACKUP_GIT_NO_NETWORK` | 否 | 设为 `1` 时拒绝任何 https 地址的推送与还原，只允许 `file://` 或本地路径。测试与演练用 |

## 子命令

### init

```sh
backup.py init [--dry]
```

**纯本地**：写 `.gitignore`（固定内容，排除 `bak/` 与缓存）、`git init`、设提交身份。不联网、不配远程、不读 token。

### remote

```sh
backup.py remote --url <url> | --show [--dry]
```

| 选项 | 说明 |
|---|---|
| `--url` | 仓库地址；省略则用 `BACKUP_GIT_REPO` 拼 |
| `--show` | 只打印当前 `origin` 与解析出的地址 |
| `--dry` | 只打印将设置的值 |

设置时若已设 token，顺带跑 `ls-remote` 验证可达。

### backup

```sh
backup.py backup [--local] [--dry] [-m <message>] [--remote <url>]
```

| 选项 | 说明 |
|---|---|
| `--local` | 只提交不推送，仍然改名再恢复 |
| `--dry` | 只列出将要备份的仓库，**不改名、不提交** |
| `-m` | 自定义提交信息，须过 Angular 校验 |
| `--remote` | 覆盖推送地址 |

流程：

1. 同步 `.gitignore`；修复上次异常中断残留的 `.git-backup`
2. `memory/` 脱敏（静默）
3. 所有 `.git` → `.git-backup`；所有子目录 `.gitignore` → `.gitignore-backup`
4. `git add -A` → 生成提交信息 → `commit`
5. `git fetch` 取远程比对历史：远端领先或分叉即终止
6. `push`
7. **回验**：`clone --depth 1` 到临时目录，改回名字后**以本地内容为基准**做三方比对：远程缺文件 = 失败，同名内容不同 = 失败，远程多出 = 只提示（来自更早的备份）
8. `finally` 恢复原名

改名范围：挂载根下**任意层级**，含嵌套仓库；根目录自己的 `.git` 与 `bak/` 内的不动。

**提交信息**沿用 Angular：类型固定 `chore`、范围固定 `backup`，主题 ≤50 字只报数量，明细放正文。

**回验失败**（`verify_remote`）的三种原因：

| 提示 | 含义 |
|---|---|
| 克隆失败 | 远程不可达或 token 无读权限 |
| 远程缺少 N 个本地文件 | 推送没生效或只推了一半，远程是残缺副本 |
| 远程有 N 个文件与本地内容不同 | 远程版本落后于本地，备份不可信 |
| 有 N 个子仓库无法读取历史 | `.git` 内容损坏，还原后不可用 |

方向不能反：本地是源、远程是副本，**按本地检查远程**（远程有而本地没有的只提示，不算失败）。

### scan

```sh
backup.py scan [--fix]
```

扫描 `memory/`，只报打码片段，不打印明文。`--fix` 就地打码。覆盖 API key、GitHub/AWS/Slack token、JWT、Bearer、私钥、长十六进制、手机号、邮箱、密码赋值、账号名。默认打码留首尾各一个字，密码与凭据全星号。

### restore

```sh
backup.py restore [--remote <url>] [--dry]
```

还原前判断本地状态（`guard_restore_target`）：

| 本地状态 | 处理 |
|---|---|
| 顶层有 `.git` | 现有条目整体移进 `bak/<YYYY-MM-DD_HH-MM>/`，再铺回备份 |
| 无 `.git` 且目录为空 | 直接整份铺入，不建 `bak/` |
| 无 `.git` 但目录非空 | 停下，退出码 `6`，列出清单让用户决定 |

流程：`clone --depth 1` 到 `/tmp/minis-restore-*` → `.git-backup` 改回 `.git`、`.gitignore-backup` 改回 `.gitignore` → 按上表处理 → 删临时目录。

## 退出码

| 码 | 含义 | 常见原因 |
|---|---|---|
| 0 | 成功 | — |
| 1 | 执行失败 | git 命令失败、推送被拒、**回验失败** |
| 2 | 用法错误 | 无子命令、未知参数 |
| 3 | 找不到挂载目录 | `--mount` 指向不存在的路径 |
| 4 | 仓库未初始化 | 没跑过 `init` |
| 5 | 缺 `BACKUP_GIT_TOKEN` / `BACKUP_GIT_REPO` | 推送或还原但变量缺失、格式不对 |
| 6 | 需用户决定后才能继续 | `restore` 时本地无 `.git` 但目录非空 |

## 已知限制

1. **`.git-backup` 里是二进制对象**，GitHub 网页上打不开——这是 git 的格式所限，不影响其他文件浏览。
2. **改名期间仓库不可用**：`.git` 变成 `.git-backup` 的几秒内，那个目录不是 git 仓库。脚本用 `try/finally` 保证恢复，异常中断后下次 `backup` 会自动修复。
3. **还原后子仓库的 `git status` 可能显示 `D` 与 `??`**：索引记的是 `.git-backup` 旧路径，改回 `.git` 后自然错位。下次 `backup` 改名时即恢复。
4. **首次备份体积最大**：要把所有 objects 传一遍；之后每次只传变化的对象。
5. **权限位丢失**：挂载盘不保留 unix 权限，写入的文件模式是默认值。
6. **token 只从环境变量读**，不落盘、不进提交；输出里的 token 替换成 `***`。
7. **不做增量去重之外的优化**：大文件改动仍会产生与该文件等大的新对象。
