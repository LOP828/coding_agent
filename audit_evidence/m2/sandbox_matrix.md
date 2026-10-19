# R-M2-02 调用前沙箱实测

实际版本：codex-cli 0.163.0；后端：本机 WSL/Linux。以下均为无模型命令实跑，模型调用次数为 0。Windows 原生沙箱未验证。

基准配置来自 docs/M1/Codex_Harness_Write_Restrictions.md。最终命名权限将候选目录设为可写、project_config.py 和 protected 设为只读、控制仓库和证据目录设为 none，命令网络禁用。完整参数、目标、退出码、stdout/stderr、前后快照与差异见 runtime_evidence.zip 中对应 result.json。

实测与 Executor 使用同样的环境清理、环境配置加载及显式覆盖；sandbox-proof.json 绑定版本、权限模板和配置哈希。具体绝对路径按一次性副本替换。

| 配置 | 项目 | 退出码 | 实测观察 | 文件变化 | 分类 |
|---|---|---:|---|---|---|
| named | allowed_write | 0 | 已实测：命令已启动 | config_loader.py | 允许路径写入成功（正向对照） |
| named | protected_write | 1 | 已实测：命令已启动 | 无 | 沙箱直接阻止 |
| named | allowed_new | 0 | 已实测：命令已启动 | allowed/new.txt | 允许路径写入成功（正向对照） |
| named | protected_new | 1 | 已实测：命令已启动 | 无 | 沙箱直接阻止 |
| named | undeclared_new | 0 | 已实测：命令已启动 | undeclared.py | 沙箱未阻止、仅 M1 事后检测 |
| named | allowed_rename | 0 | 已实测：命令已启动 | allowed/existing.txt, allowed/moved.txt | 允许路径写入成功（正向对照） |
| named | rename_to_protected | 1 | 已实测：命令已启动 | 无 | 沙箱直接阻止 |
| named | rename_from_protected | 1 | 已实测：命令已启动 | 无 | 沙箱直接阻止 |
| named | replace_protected_file | 1 | 已实测：命令已启动 | 无 | 沙箱直接阻止 |
| named | move_to_protected | 1 | 已实测：命令已启动 | 无 | 沙箱直接阻止 |
| named | move_from_protected | 1 | 已实测：命令已启动 | allowed/moved.txt | 沙箱直接阻止 |
| named | link_allowed | 0 | 已实测：命令已启动 | allowed/existing.txt, allowed/link.txt | 允许路径写入成功（正向对照） |
| named | link_protected | 1 | 已实测：命令已启动 | allowed/link.txt | 沙箱直接阻止 |
| named | link_new_protected | 1 | 已实测：命令已启动 | allowed/link.txt | 沙箱直接阻止 |
| named | create_link_protected | 1 | 已实测：命令已启动 | 无 | 沙箱直接阻止 |
| named | child_allowed | 0 | 已实测：命令已启动 | config_loader.py | 允许路径写入成功（正向对照） |
| named | child_protected | 1 | 已实测：命令已启动 | 无 | 沙箱直接阻止 |
| workspace | allowed_write | 1 | 已实测启动失败；操作未验证 | 无 | 未证实/受阻 |
| workspace | protected_write | 1 | 已实测启动失败；操作未验证 | 无 | 未证实/受阻 |
| workspace | allowed_new | 1 | 已实测启动失败；操作未验证 | 无 | 未证实/受阻 |
| workspace | protected_new | 1 | 已实测启动失败；操作未验证 | 无 | 未证实/受阻 |
| workspace | undeclared_new | 1 | 已实测启动失败；操作未验证 | 无 | 未证实/受阻 |
| workspace | allowed_rename | 1 | 已实测启动失败；操作未验证 | 无 | 未证实/受阻 |
| workspace | rename_to_protected | 1 | 已实测启动失败；操作未验证 | 无 | 未证实/受阻 |
| workspace | rename_from_protected | 1 | 已实测启动失败；操作未验证 | 无 | 未证实/受阻 |
| workspace | replace_protected_file | 1 | 已实测启动失败；操作未验证 | 无 | 未证实/受阻 |
| workspace | move_to_protected | 1 | 已实测启动失败；操作未验证 | 无 | 未证实/受阻 |
| workspace | move_from_protected | 1 | 已实测启动失败；操作未验证 | 无 | 未证实/受阻 |
| workspace | link_allowed | 1 | 已实测启动失败；操作未验证 | 无 | 未证实/受阻 |
| workspace | link_protected | 1 | 已实测启动失败；操作未验证 | 无 | 未证实/受阻 |
| workspace | link_new_protected | 1 | 已实测启动失败；操作未验证 | 无 | 未证实/受阻 |
| workspace | create_link_protected | 1 | 已实测启动失败；操作未验证 | 无 | 未证实/受阻 |
| workspace | child_allowed | 1 | 已实测启动失败；操作未验证 | 无 | 未证实/受阻 |
| workspace | child_protected | 1 | 已实测启动失败；操作未验证 | 无 | 未证实/受阻 |

命名配置：5 项允许操作成功，11 项受保护操作直接受阻，1 项未声明文件创建成功并由 M1 事后检出。move_from_protected 在删除源失败前已复制到允许目录；link_protected/link_new_protected 已在允许目录创建链接，但目标写入受阻。不得把这些行表述为完全无副作用。

传统 workspace-write 配置的 17 项均在命令启动前失败（default_permissions requires a [permissions] table）；这些不是禁止写入生效的证据。

补充实测（原始记录位于压缩包 boundary-extra/）：

| 项目 | 结果 | 判定 |
|---|---|---|
| 单文件 config_loader.py 可写根 | bubblewrap 启动失败，退出 101；前后未变化 | 未证实/受阻，不承诺单文件白名单 |
| 读取控制仓库任务说明 | 命令已启动，读取被拒，退出 1 | 本次读取受沙箱直接阻止 |
| 读取证据目录 sentinel | 命令已启动，读取被拒，退出 1 | 本次读取受沙箱直接阻止 |

一次配置对齐尝试使用了 sandbox 不支持的 --strict-config，全部启动失败；保留在 diagnostic-unsupported-strict-config/，最终配置已移除该选项。这些失败不作为边界生效证据。

最终配置不是严格的允许文件白名单：仓库其余位置可写，M1 继续检查未声明路径和 Git 元数据变化。验证候选的 Python 子进程仅具进程边界及材料哈希复核，不等同于该 Codex 沙箱，更不等同于完整 OS 隔离。第 9 类单条合法输出伪造仍为已知误通过。

首次真实 Executor 尚未执行；本表不能证明模型本次可用、任务完成或端到端成功。模型缓存列出 gpt-6-luna 与 gpt-6-sol 及 medium；选择 Luna，未发起推理探测。
