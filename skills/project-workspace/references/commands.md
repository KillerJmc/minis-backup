# 命令参考

脚本：`/var/minis/skills/project-workspace/scripts/ws.py`

## 退出码

| 码 | 含义 |
|---|---|
| 0 | 正常 |
| 1 | 具体失败（目录被占用、重名、迁移冲突） |
| 2 | 用法错误（参数缺失、非法工程名、新旧同名） |
| 3 | 没有外部挂载 |
| 4 | 未关联工程 / 旧工程不存在 |

## 命令签名

按功能分组，命令只是实现手段。

**项目绑定**

```sh
ws.py auto [--json]      # 开场：按分组名建/绑工程，列出目录内容
ws.py new <名字>          # 建空目录并绑定本会话
ws.py link <名字>         # 绑定已存在的工程
ws.py bootstrap [--json] # 仅准备挂载结构（projects/ skills/），开场 auto 会自动调用
```

**项目迁移**

```sh
ws.py migrate [--dry]               # 免参数：新名=当前分组，旧名=.project-prev/.project
ws.py migrate <旧名> <新名> [--dry]
ws.py migrate <新名> [--dry]        # 旧名取 .project 关联
```

**项目查询**

```sh
ws.py list
ws.py which
```

**资源同步**

```sh
ws.py sync [--dry] [--push|--pull] [技能名]
```

`auto --json` 结构：

```json
{"ok": true, "group": "工程名", "project": "/path/to/projects/工程名",
 "created": false, "contents": "目录树文本", "hint": "改名提示或空串"}
```

失败时：`{"ok": false, "reason": "no-mount|no-group-api|dir-error|bad-name", "message": "…"}`

## sync 语义

| 参数 | 行为 |
|---|---|
| 无 | 技能双向补缺（冲突保留 app 版）；记忆按 mtime 取新 |
| `--push` | 以 app 为准覆盖外部 |
| `--pull` | 以外部为准覆盖 app；外部缺失时不会清空内部 |
| `--dry` | 只打印将要做什么 |

权威源：`/var/minis/skills/`、`/var/minis/memory/`；镜像是 `<挂载>/skills/`、`<挂载>/memory/`。

## 联结点

`/var/minis/workspace/.project` 存当前 chat 关联的工程名，**每个 chat 独立**，所以同一工程可被多个 chat 关联。

## 迁移细节

- 冲突判定：目标侧已存在同一相对路径（文件或目录，不看内容）= 冲突；没有「跳过重复」这回事。
- 有任一冲突 → 整体中止，零文件移动、两边目录原样（`--dry` 同样返回 rc=1）。
- 四象限：旧无新有→复用；旧无新无→创建；旧有新无→建+复制；旧有新有→复制合并（同名中止）。
- 复制语义：用 `copy2` 复制（symlink 保持为链接），**旧工程永不删除**；一个分组有多个会话，别的会话可能仍在用。
- 迁移成功且当前 chat 关联的是旧名 → 自动改关联到新名。
- 旧目录清空后删除；嵌套空目录一并清理。
- 不做三方合并、不自动覆盖。

## 环境变量（测试用，勿在生产路径依赖）

| 变量 | 作用 |
|---|---|
| `WS_MOUNTS` | 覆盖 `/var/minis/mounts` |
| `WS_APP_SKILLS` / `WS_APP_MEMORY` | 覆盖 app 内权威源 |
| `WS_LINK_FILE` | 覆盖 `.project` 联结点 |
| `WS_SESSION_GROUP` | 伪造会话分组（免调 CLI） |
| `WS_CLI` | 指定 `minis-sessions-cli` 路径 |

## 已知限制

- root 下 `chmod 555` 无法模拟只读挂载，失败路径用「`projects` 被同名文件占据」等价验证。
- 外部挂载上不能用 `shutil.rmtree`（符号链接报错），删除一律走 `rm_tree()`。
- 工程名同时是目录名：含 `/`、`\`、`..` 或以 `.` 开头会被拒绝（rc 2）。
- `minis-sessions-cli status` 的 JSON 是双层嵌套，取值用递归查找（已封装）。

## 回归测试

```sh
cd /var/minis/skills/project-workspace && python3 tests/run.py            # 全部
python3 tests/run.py -g C                                                 # 单组
```

66 个场景（A–G 七组），全在 `/tmp/ws-test` 沙箱运行，末行须为 `失败 0 项`。
场景清单、沙箱变量、新增用例约定见 `tests/README.md`。
