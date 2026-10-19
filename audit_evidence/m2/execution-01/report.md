# M2 本次真实闭环结果

任务 M2-TASK-01（provider 校验）本次完成：Executor → Runner → 确定性判定为 **PASS / NONE**。
共 1 次尝试，没有触发重试；累计调用模型的 Codex exec 为 **1 / 10**。无模型沙箱命令不计入。
CNC 第二任务经 MK 取消，**MK 取消，未执行**，不视为未完成项。此决定优先于冻结任务说明中的原范围；冻结文件未修改。

实际使用 codex-cli 0.163.0、gpt-6-luna、medium、300 秒超时，退出码 0、未超时、stderr 为空。
完整提示词和 argv 与 MK 确认的 prepared-request 完全一致；使用先前实测的命名权限，未使用跳过沙箱或完全访问参数。
模型的自述仅作执行轨迹，判定来自 Runner 的独立观测比较和文件/Git 快照。

| 项目 | 实际结果 |
|---|---|
| Executor 改动 | 仅 config_loader.py；把 NotImplementedError 替换为缺少 provider 时抛出 MissingProviderError，否则原样返回 config |
| 缺少 provider | 子进程正常退出，观测到 MissingProviderError；按类名匹配，PASS |
| 已有 provider | 子进程正常退出，返回原配置，PASS |
| 修改路径检查 | 仅允许文件变化，DIFF_ALLOWLIST 为 PASS |
| Git 元数据 | 未变化，未创建提交 |
| 判定与重试 | PASS / NONE；STOP_AFTER_PASS，无重试 |
| 依赖环境 | 验证前后检查未发现变化 |

演示仓库在 `/mnt/d/project/coding_agent_m2_runs/provider-c35176459a33/attempt-1`；运行证据在同级 `evidence`，均在控制仓库之外。
`executor.patch` 保存实际补丁；`executor-trace.jsonl` 保存完整 CLI 轨迹；`verification_report.json` 与 `workflow.json` 保存判定及流程结果。
`runtime_evidence.zip` 包含请求、账本、执行输出、逐用例输入和观测、比较结果、快照审计、候选前后文件及可信任务夹具；`archive_manifest.json` 给出逐文件哈希。
归档未包含认证文件或配置原文。

执行命令（已执行，勿将重复运行当作本次结果）：

```bash
/tmp/coding-agent-m1-category8-s6qqkjt0/bin/python3.11 -m coding_agent.m2_run execute --prepared-request /mnt/d/project/coding_agent_m2_runs/provider-c35176459a33/evidence/prepared-request.json --approved-sha256 6cb1a054af7a6d9391c9ac7fe7e02d5af1928257cdd8f8394f8bdc8f2b82f418
```

默认测试在调用前的代码提交 `ec93843200fda1d2c3efc696779dee5dde1f16d2` 上运行：

| 环境 / 命令 | passed | failed | errors | skipped |
|---|---:|---:|---:|---:|
| Linux Python 3.11.15，python -m pytest | 183 | 0 | 0 | 0 |
| Windows Python 3.13.7，python -m pytest | 183 | 0 | 0 | 0 |

Windows 为 CP936、core.autocrlf=true、未设置 PYTHONUTF8。原有 129 项保留，新增 54 项，无替换。
本轮仅同步 CNC 状态元数据和说明文档，语法检查通过；未重复运行默认全量测试。真实任务验证的两条行为检查与路径检查均已在本轮实际执行并通过。

遗留问题与边界：

- **读取权限过宽（MK 本次接受）**：`:root="read"` 默认允许读取整个文件系统，显式 none 的控制仓库和证据目录除外，不符合读权限仅限项目相关目录的原则。本次因命令网络关闭、任务简单而接受；后续应收紧读取目录并重做沙箱实测。此限制未在本轮修复。
- 当前目录写权限不是严格单文件白名单；未声明的新文件仍可写，由 M1 事后检出。单文件可写根配置启动失败，不能宣称已验证。
- 候选 Python 观测进程不是 OS 沙箱；第 9 类单条合法观测伪造仍可能误通过。旧 pytest 第 8 类与样本 04 按明确范围保留已知误通过。
- 本次 Codex 沙箱证据仅覆盖 Linux；Windows 默认测试通过不等于原生 Windows 沙箱验证。
- 本次为使用明确标记的合成审批夹具完成的一次 provider 演示，不代表一般成功率或可靠性。

原调用前归档保留历史状态，未覆盖；本目录是 MK 范围调整后的最终闭环报告。
