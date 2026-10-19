# M3 最终验收摘要

M3 控制层验收完成。MK 已通过控制层批准第 4 次提案入图；两个原子任务仍为 PENDING，尚未执行。

批准绑定提案哈希：`d36601314fea78e5204216afbe84ac8937f5739d34299a67458409d09f19f04a`；地图版本 4 → 5。批准命令及事件见本目录 `approval-command.json`、`approval-event.json`。

## 完整测试

| 环境 | passed | failed | errors | skipped | 耗时 |
|---|---:|---:|---:|---:|---:|
| Linux / Python 3.11.15 | 260 | 0 | 0 | 0 | 228.13 秒 |
| Windows / Python 3.13.7 | 260 | 0 | 0 | 0 | 494.23 秒 |

两端均执行完整 `python -m pytest`。Windows 原生 CP936、`PYTHONUTF8` 未设置、`git core.autocrlf=true`。原有 183 项测试保留，M3 共 77 项，无替换项。

## 模型调用（4/5，剩余 1 次不再使用）

| 次数 | 需求 | 结果 | MK 决策 |
|---|---|---|---|
| 1 | R-003 | API 400：接口 Schema 不支持 uniqueItems，未生成提案 | 无提案 |
| 2 | R-003 | 完整结构校验通过；questions_for_mk 为空 | REJECTED：漏提问题、错误标为 EXPLICIT |
| 3 | R-003 | 完整结构校验通过；提出 2 个问题 | REJECTED：问题已由 MK 答复为 R-004 |
| 4 | R-003 + R-004 | 完整结构校验通过；2 个原子任务；questions_for_mk 为空 | APPROVED，已入图 |

全部调用使用 GPT-6 Sol / medium、Codex CLI 0.163.0、实测只读沙箱；无自动重试。调用单位为 AI_BACKED_CODEX_EXEC_INVOCATION，含第 1 次失败。完整参数、原文与校验分别保存在 planning-01 至 planning-04；不据此推断可靠性或成功率。

## 最终状态

| 节点 | 父节点 | 状态 |
|---|---|---|
| stage | 无 | READY |
| validate_provider | stage | PENDING |
| validate_timeout | stage | PENDING |

焦点为 stage，无运行任务、无暂存发现、无未覆盖冻结需求（仅结构检查）。第 2、3 次提案原文和 REJECTED 记录均保留。完整状态见 ../../../exports/status.md。

## 已知限制与下一阶段

- 结构校验不能判断 EXPLICIT 是否直接受原文支持，也不能证明规划 AI 已列出全部未明确事项。第 2 次真实提案提供了实测证据。
- 提案没有任务依赖字段；validate_timeout 依赖 validate_provider 定义的 InvalidConfigError，须由 MK 按顺序启动。
- 缺少 provider 且 timeout 不合法等组合情况的优先级未被需求规定，规划 AI 未提出。
- 任务卡草稿不含验收用例；用例编写与审批留待下一阶段，当前不能直接执行。
- MK 入口信任本地操作者；历史哈希不是防同用户完全改写的不可变介质。M2 候选进程的边界及停止机制限制仍保留。原生 Windows Codex 沙箱未实测；真实规划沙箱实测环境为 Linux。

具体记录见 ../../../docs/M3/Known_Limitations.md。

## 实现与既有演示

新增确定性任务地图/状态机、事件存储、发现暂存、权限绑定、只读规划适配器、状态报告、需求追加版本管理及 M3 Schemas/测试；接口 Schema 与完整控制层 Schema 分离。修改文件清单见 changed-files.txt。冻结 M3 任务说明与 R-003 保持不变；R-004 按 MK 原文冻结。

此前纯脚本演示使用真实 Runner 得到 PASS、子任务 DONE 后焦点返回父节点、发现进入暂存区、越权兄弟执行请求被拒绝，并报告 R-003 未覆盖；无模型调用。该演示证据保留于原 M3 归档，本次不重复运行。完整测试另覆盖真实 Runner 与同次 RUNNING 内的重试。

最终状态、历史、四次调用和沙箱证据存入 runtime-final.zip，102 个条目已校验；runtime-manifest.json 列出逐文件 SHA-256。旧测试、Schema、m0.py 与既有归档共 101 个文件经基线比较未改动。

## 本地提交

| 提交 | 说明 |
|---|---|
| `38df9db` | M3 需求，MK 已确认 |
| `98438d0` | M3 确定性任务地图与只读规划准备 |
| `af9885e` | M3 调用前验收与只读沙箱实测证据 |
| `f600100` | M3 规划原始输出隔离与首次调用授权记录 |
| `88ee408` | M3 首次规划调用失败与原始证据记录 |
| `c42a130` | M3 拆分接口 Schema 并记录第二次规划调用授权 |
| `0dfea8b` | M3 第二次规划提案与完整校验证据 |
| `1853513` | M3 记录规划语义限制与第三次调用授权 |
| `9288b0d` | M3 第三次规划提案与待澄清问题证据 |
| `e72134c` | M3 冻结 R-004 并记录第四次规划调用授权 |
| `58fde0d` | M3 第四次规划提案与完整校验证据 |
| `48f1585` | M3 批准第四次提案入图并导出状态与限制 |
| 本报告所在提交 | M3 最终跨平台验收与闭环证据 |

全部为本地提交，未 push。
