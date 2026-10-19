# M3 已知限制

## 规划语义与结构校验之间的缺口（MK 确认）

第 2 次真实规划针对冻结需求 R-003 生成提案；原完整 Schema 和结构规则全部通过，MK 审查后明确不批准。
保留[提案原文](../../audit_evidence/m3/planning-02/proposal.json)和[完整校验结果](../../audit_evidence/m3/planning-02/full-validation.json)，不改写或替换该次输出。

MK 记录的两条观察：

- 规划 AI 未将需求中的未明确事项列入 `questions_for_mk`，输出了空列表。
- `validate_provider` 的属性“其他 provider 值触发 InvalidConfigError”并非需求原文明确规定，却被标为 `EXPLICIT`。提案原文的对应表述为“其他已提供的 provider 值触发 InvalidConfigError”。

结构校验全部通过，说明当前结构校验无法发现此类问题：它能验证字段、引用、派生理由是否填写、图结构和路径规则，不能判断行为是否由需求原文直接支持，也不能证明规划 AI 已找出所有未明确事项。`EXPLICIT` 是规划 AI 的声明，`questions_for_mk: []` 不等于需求无歧义；结构 PASS 不等于语义审查通过。

第 3 次调用仅在提示词中增加 MK 指定的一般性规则，要求 EXPLICIT 行为直接对应原文，补充行为标为 DERIVED 并写明理由或列为待澄清问题，不确定时优先提问。提示词不包含上述具体观察或任何针对 R-003 的提示。该调整是规划引导，不是确定性语义验证，也不改变冻结需求；提案仍须 MK 审查后才能入图。

## 第 4 次提案批准后的限制（MK 确认）

- 提案格式没有任务依赖字段；本次 validate_timeout 依赖 validate_provider 中定义的 InvalidConfigError，需由 MK 按顺序启动。
- 规则组合情况（如缺少 provider 且 timeout 不合法）的优先级未在需求中规定，规划 AI 未提出。
- AI 规划出的任务卡草稿不含验收用例，尚不能直接执行；用例的编写与审批留待下一阶段。

第 4 次提案已经 MK 批准入图，两个原子任务保持 PENDING，尚未启动。上述限制不通过补写冻结需求、改写提案原文或宣称结构校验能够识别来消除。
