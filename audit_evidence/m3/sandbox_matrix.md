# M3 实际沙箱证据

本机 codex-cli 0.163.0，Linux/WSL。全部为直接 sandbox 命令，不调用模型。Windows 原生沙箱未实测；Windows pytest 验收不替代它。

最终只读配置：:root=none、:minimal=read、Codex 安装目录及演示目录只读，控制仓库和状态目录 none，命令网络关闭，apps 和 multi_agent 禁用。

最小运行时配置参考 [OpenAI Docs Permissions](https://learn.chatgpt.com/docs/permissions)；是否生效以下表实际运行结果为准。实际 CLI 使用的 none 拼写与滚动文档的 deny 不混同。

| 操作 | 启动 | 退出码 | 实测分类 |
|---|---|---:|---|
| read_allowed | True | 0 | POSITIVE_READ |
| write_existing | True | 1 | SANDBOX_DENIED |
| new_file | True | 1 | SANDBOX_DENIED |
| delete | True | 1 | SANDBOX_DENIED |
| rename | True | 1 | SANDBOX_DENIED |
| replace | True | 1 | SANDBOX_DENIED |
| link_write | True | 1 | SANDBOX_DENIED |
| child_write | True | 1 | SANDBOX_DENIED |
| read_state | True | 1 | SANDBOX_DENIED |
| write_state | True | 1 | SANDBOX_DENIED |
| read_controller | True | 1 | SANDBOX_DENIED |
| executor_allowed_write | True | 0 | POSITIVE_WRITE |
| executor_state_read | True | 1 | SANDBOX_DENIED |
| executor_state_write | True | 1 | SANDBOX_DENIED |

POSITIVE_READ：项目文件成功读取。POSITIVE_WRITE：仅补充 Executor 可写配置下允许文件成功写入。SANDBOX_DENIED：命令已启动，目标操作被拒；只读项目对应前后快照相同。

三个 executor_ 行使用 M2 写入配置加外部状态目录 none，是对 M2 已有完整写入矩阵的补充；不能把它们误认作只读规划配置允许写入。

最终只读证明和 Executor 补充证明分别为压缩包 sandbox/readonly-83e7a33c6a4c/readonly-proof.json 与 executor-proof.json。逐项目录包含完整命令、配置、目标操作、stdout/stderr、退出码和前后文件哈希快照。

启动失败历史（全部保留原始证据，不算成功拒绝写入）：

- readonly-e801afccf816：未包含 Codex 自身运行文件，命令未启动。
- readonly-6410cbc76c7d：手工运行时路径下动态加载器别名不可用；直接加载器诊断另外保存。
- readonly-d6c83a48424e：:minimal 与手工 /etc/localtime 挂载冲突，未启动。
- readonly-5182d8472b5e：收敛运行时后的只读矩阵通过，尚未加入最终能力开关及 Executor 补充项。
- readonly-591be6b06202：最终只读矩阵通过；Executor 因状态祖先与证据子目录重复拒绝挂载而启动失败。
- readonly-83e7a33c6a4c：最终配置与重复挂载修正后，全部要求的操作通过实测。

最终调用绑定配置文件哈希、相关环境哈希、权限模板、Schema 哈希及 CLI 版本，漂移时拒绝执行。

边界：证明适用于本机经这些入口启动的沙箱命令；不证明任意宿主进程不能改控制目录，也不证明 M2 候选 Python 进程有 OS 级隔离。哈希复核是事后检测。真实规划尚未执行，不能据此声称模型提案有效。
