# M0.2 迁移验收记录

## 仓库与迁移

- 独立仓库：Linux/WSL `/mnt/d/project/coding_agent`；Windows `D:\project\coding_agent`。
- 实际分支：`master`，新建本地仓库；无 remote，不 push。
- 参考来源：`docs/coding_agent_m0_spec_v0_2_handoff.zip`，保持原文件不变。
- 核心迁移：`checks/spec_reference.py` → `src/coding_agent/m0.py`。
- 既有回归：`checks/test_spec_regressions.py` → `tests/test_spec_regressions.py`。
- 差异证据：`audit_evidence/m0_migration.diff` 与
  `audit_evidence/test_spec_regressions_migration.diff`。
- 三个 Schema、十份 JSON 夹具、五份候选代码、两份冻结测试，共 20 个副本，
  与压缩包逐字节一致；清单与 SHA-256 见 `audit_evidence/frozen_copy_verification.json`。
- 未修改任务卡路径、manifest、模拟批准记录或任何批准摘要。
- 当前系统标识为 Codex（基于 GPT-6）；会话未提供可核实的具体模型变体和推理档位，
  因而不声称实际运行的是 GPT-6 Sol / High，也未修改外部模型配置。

正式接口独立处理包内 Schema 资源和测试清单的 `test_root`。除这些资源与导入
调整之外，参考实现的规则分支保持不变。现有回归的断言没有放宽或删除。
默认收集只显式排除被测数据 `tests/data`；未引入额外排除目录、skip 或 xfail。

## 实际默认验收

两端均在独立虚拟环境安装 `.[dev]`，运行依赖为 jsonschema 4.26.0，
开发依赖为 pytest 9.0.2。实际验收命令统一为 `python -m pytest`。

| 平台 | Python | passed | failed | errors | skipped | 退出码 |
|---|---|---:|---:|---:|---:|---:|
| Linux / WSL | 3.11.15 | 80 | 0 | 0 | 0 | 0 |
| Windows 原生 / CP936 | 3.13.7 | 80 | 0 | 0 | 0 | 0 |

80 项由原有 70 项回归和新增 10 项集成检查组成：根目录分离 1 项、
准入拒绝后的 Executor/报告调用计数 4 项、已知候选执行 4 项、独立 oracle 1 项。

Linux 激活 `.venv` 后从仓库根目录运行 `python -m pytest`。
系统 Python 缺少 ensurepip，实际通过 uv 创建虚拟环境并安装项目依赖。
Windows 在 PowerShell 中进入 `D:\project\coding_agent`，移除 `PYTHONUTF8` 后运行
`& .\.venv-windows\Scripts\python.exe -m pytest`，它是原生 Python，不是 WSL Python。
Windows 记录确认 `locale_encoding=cp936`、`utf8_mode=0`、`PYTHONUTF8=null`。
Windows Git 读取到的 `core.autocrlf=true`；未修改全局 Git 设置。

各平台完整输出和环境分别见：

- `audit_evidence/linux/acceptance.log`、`acceptance_summary.json`。
- `audit_evidence/windows/acceptance.log`、`acceptance_summary.json`。

## 样本真实结果

以下结果在 Linux 与 Windows 各自实跑，分别保存原始失败输出、JUnit XML、
退出码和摘要。主线测试断言这些预期结果，因此主线 80 passed 不等于所有候选正确。

| 样本 | 机器 gate / route | 候选测试 passed / failed | 子进程退出码 |
|---|---|---|---:|
| 01 | PASS / NONE | 2 / 0 | 0 |
| 02 | HARD_FAIL / EXECUTION_FAIL | 1 / 1 | 1 |
| 03 | HARD_FAIL / EXECUTION_FAIL | 2 / 0 | 0 |
| 04 已批准错误契约 | PASS / NONE | 2 / 0 | 0 |
| 04 独立原文 oracle | 不注入任务 gate | 1 / 1 | 1 |

每组子进程 errors=0、skipped=0。场景 04 的评测标签保留为
`FALSE_PASS_EXPECTED_KNOWN_GAP`；没有改成 PENDING，也没有声称语义错误已被检出。
其失败详情在两个平台目录的 `04_independent_source_oracle.log` 和 `.xml` 中。
场景 02 的失败详情为 `02_requirement_violation_declared_tests.log` 和 `.xml`。

机器 gate 使用冻结合成报告与可信合成 changed_paths。子进程执行结果作为独立
实跑证据保存，不把合成报告冒称生产 Runner 生成的报告。

## 能力边界与交付

M0 已实现：三个 Schema、来源与哈希验证、结构覆盖、批准和范围授权核验、
测试内容 manifest、执行前结构准入、路径策略、纯函数 gate 汇总和报告绑定。
无效准入通过调用计数证明不执行后续 stub、不签发报告。

M1 尚需真实 Runner、可信 Git 变更与测试证据采集、控制侧审批存储和 Executor
权限隔离。当前执行工具只运行包内已知演示代码，临时目录不等于沙箱。

M2 尚缺独立语义审查。M1 隔离不能修复错误契约，未来模型能否识别场景 04 未被验证。
这里的 80 项通过不是生产可靠性、错误拦截率或权限安全性的测量。

交付文件包括正式模块与 Schema、默认回归和集成测试、原样冻结样本、包配置、
README、本文及分平台审计证据。本地提交后可用 `git show --stat HEAD` 和
`git show HEAD -- src tests pyproject.toml README.md VALIDATION.md` 查看实际改动；
提交哈希在最终交付消息中给出，避免在提交内容中自引用尚未生成的哈希。

全量 `git diff --cached --check` 提示原始日志末尾空行和已保存 unified diff
的空白上下文行；为保留真实证据未改写这些文件。代码、测试、配置及说明文件
另行执行 whitespace 检查。
