# 推送凭据设计

> 2026-11-24 · 结论：只有 **2 个必填**变量——`BACKUP_GIT_TOKEN`（凭据）与 `BACKUP_GIT_REPO`（作者名/仓库名组合）。

## 为什么需要变量

推送走的链路是：

```
backup.py backup
  → git commit  （需要作者身份）
  → git push    （需要 GitHub 凭据）
```

两件事都要外部信息，脚本不能也不该把它们写死或落盘。

## 变量清单

| 变量 | 必填 | 格式 | 用途 |
|---|---|---|---|
| `BACKUP_GIT_TOKEN` | **是** | `github_pat_...` 或 `ghp_...` | HTTPS 推送/克隆认证 |
| `BACKUP_GIT_REPO` | **是** | `作者名/仓库名`，如 `killerj/myminis-backup` | 拼出 `https://github.com/<作者>/<仓库>.git`，并校验推送目标 |

两个都缺或格式不对时立即退出（码 5），不发生任何网络请求。`--local` 与 `--dry` 不需要它们。

`BACKUP_GIT_REPO` 一箭三雕：

1. **仓库地址**：`remote --url` 省略参数时据此拼地址；
2. **目标校验**：推送到网络地址前，若地址里的 owner/repo 与它不一致 → 立即终止，防止推错仓库；
3. **还原兜底**：`restore` 没配 origin 时用它拼地址。

## 为什么不再多

- **不设 `GIT_AUTHOR_*`**：作者名统一写 `Minis Agent <agent@local>`，备份提交不需要个人署名。
- **不设 `GITHUB_API_TOKEN`**：不自动建仓库、不发 API 请求。
- **不设 `GIT_SSH_KEY`**：iSH 里没装 ssh 客户端，统一走 HTTPS + token，少一条链路。

## Token 怎么建

1. GitHub → Settings → Developer settings → **Fine-grained personal access tokens** → Generate new token；
2. Repository access 只勾**要备份的那一个仓库**；
3. Permissions → Repository permissions → **Contents: Read and write**（其余全 No access）；
4. 复制 token，在 Minis 里加环境变量 `BACKUP_GIT_TOKEN`。

## 最小可用配置

```sh
BACKUP_GIT_TOKEN=github_pat_xxx
BACKUP_GIT_REPO=你的GitHub用户名/仓库名
```

## 校验链路

```sh
python3 backup.py remote --show        # 确认解析出的地址
python3 backup.py backup --local       # 只提交，不联网
python3 backup.py backup               # 先核对远端历史，再推送
```

`remote --url` 会顺带跑 `ls-remote`：token 无效时报「远程无法访问」，不会等到推送时才失败。

## 安全边界

- token 只从 `os.environ` 读取，不写配置文件、不进提交、不进 `.git/config`；
- 所有输出经 `mask()` 替换成 `***`；
- 与 `privacy.py` 的凭据扫描互补：一个是"别把新凭据写进 memory"，一个是"别把 token 打印出来"。
