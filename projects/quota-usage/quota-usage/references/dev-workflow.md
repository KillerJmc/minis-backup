# 给新平台加实现：流程与约定

本文是开发方法，不是平台接口文档。平台事实写在各平台自己的
`references/<平台>-api.md`。

## 命名约定

| 层级 | 规则 | 例 |
|---|---|---|
| 技能名 | `quota-usage`（多平台统一入口） | — |
| 平台标识 | 小写单词，同时是 `scripts/` 下的子目录名 | `minekuai` / `modelscope` / `qiniu` |
| 脚本目录 | `scripts/<平台>/`，各平台的 `quota.py` 可同名互不干扰 | `scripts/minekuai/quota.py` |
| 脚本 | 一个文件一件事 | `quota.py` / `checkin.py` / `login.py` |
| 配置 | `/var/minis/shared/quota/<平台>.json`，目录 0700、文件 0600 | `quota/minekuai.json` |
| 账号凭证 | 环境变量 `QUOTA_<平台大写>_CRED`，格式「账号；密码」或只填手机号 | `QUOTA_MIAOTOKEN_CRED` |

改名要同步五处：目录名、`SKILL.md` 的 `name`、文档里的绝对路径、
其他技能对它的引用、挂载镜像（先删旧目录再 push）。

配置路径**不跟改名**，否则已有登录态全部失效。

## 账号不写配置文件

所有平台的账号（手机号、邮箱、用户名）只从环境变量读，配置文件仅存登录态。

| 平台 | 变量 | 格式 |
|---|---|---|
| minekuai | `QUOTA_MINEKUAI_CRED` | 只填手机号 |
| modelscope | `QUOTA_MODELSCOPE_CRED` | 只填手机号 |
| qiniu | `QUOTA_QINIU_CRED` | `账号；密码` |
| miaotoken | `QUOTA_MIAOTOKEN_CRED` | `账号；密码` |

分隔符认英文分号、中文分号、空格，按第一个出现的切开；无分隔符时整段视为账号。
解析逻辑统一在 `scripts/credentials.py`，各平台脚本不得自行拆分字符串。

## 六步流程

```
① 摸清平台真实接口 → ② 判断哪些能纯 HTTP、哪些必须浏览器
→ ③ 写脚本 → ④ 小样本跑通 + 异常分支跑通
→ ⑤ 写进 SKILL.md（只写 agent 要执行的）
→ ⑥ 补测试、提交、部署
```

### ① 摸接口

浏览器打开目标页，读资源的加载记录比翻 DOM 快：

```js
performance.getEntriesByType('resource').map(r => r.name)
  .filter(u => /balance|usage|quota|token/i.test(u))
```

拿到候选后直接用 curl/urllib 试探，确认鉴权头、必要 cookie、返回包外形。

### ② 判定能不能纯 HTTP

判据是：**要不要 JS 现场签名 + 与真实 TLS 指纹同源**。

- 能纯 HTTP：读数据、查余额、访问页面触发服务端判定
- 必须浏览器：风控要求 JS 签名（魔搭的阿里 baxia 属此类，`RGV587` 拦截全部离线方案）

必须浏览器时，只把「点两次」这一步交给浏览器，校验与落盘仍走脚本，
流程写进 `references/<平台>-relogin.md`。

### ③ 脚本约定

- 只提供一个入口脚本 `quota.py` 与 `checkin.py`，二者都支持 `--json`
- 退出码全局统一：`0` 正常 ｜ `1` 网络/接口 ｜ `2` 需人工 ｜ `3` 登录失效 ｜ `4` 缺配置
- 写配置必须原子（`tmp` + `os.replace`）+ `chmod 0600`
- 写新凭证前先打一次只读接口校验，**无效不覆盖**
- **幂等**：已完成的操作直接返回，靠接口状态判断，不靠「跑过一次」
- 输出不依赖缩进或列对齐

### ④ 测试

至少四种场景，全部写进 `tests/cases.json`：

| 场景 | 做法 |
|---|---|
| 正常路径 | 真跑一次 |
| 幂等 | 连跑两次，结果一致 |
| 缺配置 | 把配置环境变量指向不存在的文件 → 期望 rc=4 |
| 登录失效 | 用过期凭证 → 期望 rc=3 |

### ⑤ 写文档

SKILL.md 只留「什么时候用、跑什么、输出怎么读、出错怎么办」。
参数、JSON 结构、退出码、平台事实全部下沉 `references/`。

### ⑥ 收尾

```sh
cd "projects/<工程>"

# 发布分两轮，由 release.py 控制，不靠记忆
python3 /var/minis/skills/skill-generator/scripts/release.py prepare <技能名>
# 把输出的确认包贴给用户，等明确点头
python3 /var/minis/skills/skill-generator/scripts/release.py confirm <snapshot>
```

`prepare` 出「变更记录 + 文件清单 + 增删行数 + snapshot」，`confirm` 先重算 snapshot 比对
（贴出后改了任何文件就拒绝），再依次 validate → 跑测试 → commit → deploy → 打包。

工具只有一份，在 skill-generator 的 `scripts/` 下，**不要复制到本工程**。
底层的 `deploy.py` 也能单独用（`--dry` 看差异、`--pack-only` 只出包），但它不做 snapshot 校验。

## 提交规范

格式沿用 Angular：`<类型>(<范围>): <主题>`，标题 ≤50 字符、不加句号、命令式。

| 类型 | 用途 |
|---|---|
| `feat` | 新功能点或行为变化 |
| `fix` | 修 bug、修文档里的事实错误 |
| `docs` | 只改文档 |
| `test` | 只加改用例 |
| `chore` | 结构、依赖、整理、`temp` 清理 |

范围用小写英文主题词（`minekuai` / `route` / `layout` / `progress` / `deploy`）。
不要自创 `update`、`调整` 这类词。

- **一次 commit 一件事**：能用一句话概括就是一件；概括不了就拆。
- 正文只写「为什么」，不重复标题里已有的「做了什么」。改了行为又改测试期望时必须写正文，
  否则后人分不清是「修正了错误期望」还是「为了让测试变绿而放宽标准」。
- `git add <路径>` 精确添加；确认整轮改动属于同一件事才用 `git add -A`。
- `temp/` 单独提交（`chore(temp): …`），不要混进代码提交。

两个仓库的触发点不同：

| 仓库 | 何时提交 |
|---|---|
| 技能仓库（`quota-usage/`） | 代码改完且测试绿了才提；改到一半不提；同一改动反复试只留最终版一次 |
| 工程仓库（外层） | 本轮有可记录的事就提：deploy 成功、有结论或新待办、做出取舍、调研沉淀 |

唯一硬绑定：**每次 deploy 成功，工程仓库必须有且仅有一次对应记录**（`docs(progress): 记录 v<版本> 发布`）。
工程仓库不能领先——记录里写「已上线」之前，deploy 必须真的成功过。

## 接一个新平台

1. `scripts/route.py` 的 `PROVIDER_MAP` 加一行域名 → 平台标识
2. `scripts/route.py` 的 `PLATFORMS` 加一条元数据（名称、别名、域名、官网、登录方式）
3. 在 `scripts/<标识>/` 放 `quota.py` 与 `checkin.py`，都支持 `--json` 并按统一退出码返回
4. 在 `references/` 放 `<标识>-api.md`（接口清单）与需要时的 `<标识>-relogin.md`
5. 补 `tests/cases.json` 用例

`list` 子命令与别名匹配会自动接上，不需要改其他代码。

## 踩坑

| 现象 | 原因 | 处理 |
|---|---|---|
| `未找到实现：.../scripts/<标识>/quota.py` | `SKILL_ROOT` 层级算错（入口在 `scripts/route.py`，需上溯两级） | 用 `dirname(dirname(abspath(__file__)))` |
| 平台脚本互相导入失败 | 从原目录整体搬迁后 `from quota import ...` 找不到 | 先 `sys.path.insert(0, 脚本所在目录)` |
| `'str' object has no attribute 'get'` | `minis-config get` 的 `value` 是 JSON 字符串 | 二次 `json.loads` |
| 测试一直绿但功能是错的 | 期望值按错误设计写的 | 先质疑期望，再改代码 |
| 分页只取到第一页 | 参数名不对（有的接口认 `page`，有的只认 `pageNum`） | 用两页对比首条 id 验证翻页真实生效 |