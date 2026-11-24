# 测试说明

`validate.py` 的回归测试：每条用例在 `/tmp/skill-generator-test/` 造一个技能目录，跑校验器，断言退出码与输出。

```sh
python3 tests/run.py              # 全部（35 项）
python3 tests/run.py -g body      # 单组：valid / meta / body / env
python3 tests/run.py -i V1,B2     # 指定用例
python3 tests/run.py -v           # 附带校验器原始输出
python3 tests/run.py --list       # 清单
```

末行须为 `合计 35 项，失败 0 项`；退出码 0 全绿 / 1 失败。

## 用例格式

```json
{
  "id": "B1", "group": "body", "name": "首句是标题 → ERROR",
  "dir_name": "demo",              // 造的目录名（默认 demo）
  "no_dir": false,                 // true = 目标目录不存在
  "files": {"SKILL.md": "..."},    // 技能目录内的相对路径 → 内容
  "parent_files": {"deploy.py": "x"}, // 上一层（工程层）的文件，默认无
  "extra": ["--json"],             // 额外参数
  "rc": 1,                         // 期望退出码
  "has": ["正文第一句是标题"],       // 输出必须包含
  "hasnt": [],                     // 输出不得包含
  "json_ok": true,                 // --json 输出须可解析
  "errors_count": 1                // 直接调用 check() 的 ERROR 数
}
```

## 覆盖

| 组 | 场景 | 条 |
|---|---|---|
| valid | 合法技能、带 references、`--json` | 3 |
| meta | 缺 triggers / 缺 frontmatter / description 超长 / name 不匹配 / version 格式 | 5 |
| body | 首句是标题 / 首句与描述不一致 / 缺功能表 / 正文超 500 行 / 出现编号 | 5 |
| env | 目录不存在 / 有 scripts 无 tests / 孤立目录含 `.git` | 3 |
| changelog | 缺文件 / 版本不一致 / 降序正确 / 升序告警 / 无版本行 / 条目缺冒号 | 6 |
| normalize | 合规工程 / 缺文件预演 / 命名不一致停止 / .tmp 改名提示 / --apply 落盘 | 5 |
| layout | 工程层缺文档 / 技能目录放工程文件 / 独立技能不报工程层 / 工程层齐全 / docs 未引用 / docs 已引用 / 工作副本有 .git / 技能目录放 WORKFLOW | 8 |

## 约定

1. **一条用例只验一件事**，失败原因能一眼定位；
2. 判定三件套：退出码、输出文案、`check()` 的 ERROR 数，缺一不算过；
3. 新增检查项时，正反各加一条（合法通过 + 违规报错）；
4. 改完先跑一次负向自检：把某条合法用例的 `rc` 改错，必须变红，再还原。

## 脚本用例

除了校验器，也可以直接跑别的脚本（`script` 字段）：

```json
{
  "id": "N2", "group": "normalize", "script": "normalize.py",
  "args": ["{dir}"],          // {dir} 会替换成沙箱里的目标目录
  "files": {"PROJECT.md": "..."},
  "rc": 0, "has": ["将新建 PROJECT.md"],
  "absent": ["PROJECT.md"]     // 断言没有真的写盘
}
```

`exists` / `absent` 用于断言磁盘结果，路径相对目标目录。
