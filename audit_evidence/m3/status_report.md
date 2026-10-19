本轮真实规划状态（尚未调用模型）：

主线/目标：配置校验扩展：只读规划
当前焦点：stage

节点：
- stage | 父：None | READY | stage

暂存区：
- 无

待 MK 决策：
- 真实规划 planning-01：等待 MK 确认完整提示词与调用参数

待 MK 澄清的问题：
- 无

未覆盖冻结需求（仅结构检查）：
- 无

纯脚本演示状态（合成夹具；Runner 实际执行）：

主线/目标：无模型脚本演示（合成夹具）
当前焦点：root

节点：
- root | 父：None | READY | root
- first | 父：root | DONE | first
- second | 父：root | READY | second

暂存区：
- first-8-finding-1-0 | OPEN | 测试发现记录，等待 MK 决定。

待 MK 决策：
- 发现 first-8-finding-1-0：等待提升或删除

待 MK 澄清的问题：
- 无

未覆盖冻结需求（仅结构检查）：
- R-003
