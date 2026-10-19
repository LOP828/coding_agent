# M2 观测协议 v2

本说明记录实现协议，不修改已冻结的 M2 任务说明。旧 M0/M1 测试与夹具原样保留，
旧 pytest 通道的第 8 类仍为已知误通过；新版数据通道另作回归。

主进程在 Executor 执行前校验 manifest、审批及 JSON 用例，并把期望值保存在内存。
新版数据格式为 coding-agent-cases-v2，检查引用仍用 cases/provider.json::用例ID。
每个用例包含 module、function、args、kwargs、expect，没有可执行测试源码。
合成审批明确标注“合成夹具（synthetic fixture）”，不代表 MK 真实审批。

每个用例启动独立的 python -I -S -B _candidate_worker.py。stdin 为 UTF-8 JSON，
包含 format、run_id、case_id、候选根路径、可信依赖路径、模块路径、函数和参数。
不传期望值、审批记录或报告路径。子进程添加控制层指定的依赖路径，使候选能够导入
pytest 等已有依赖，但不启动 pytest、不创建 pytest Config。主进程不导入候选。

stdout 必须恰好包含一个完整 JSON 对象，允许首尾空白，不允许额外日志或第二条结果：

    {"format":"coding-agent-observation-v2","run_id":"每次调用的新标识","case_id":"文件::用例ID","outcome":{"kind":"return","value":{"provider":"openai"}}}

异常观测使用 {"kind":"exception","type":"MissingProviderError","message":"任意信息"}。
**异常按类名精确比对，不比较继承关系；异常信息只有用例的 expect 明确包含 message 时才比对。**
返回值递归比较 JSON 类型和值，布尔值不等于整数。解析拒绝重复键、非有限数、
错误标识、额外字段、非法 UTF-8、超大结果及零条/多条观测，不执行 eval/pickle。
正常观测不符合期望记为 FAIL / OBSERVATION_MISMATCH；匹配记为 PASS。

导入失败、目标查找失败、非可调用目标、序列化失败、非零退出、超时或非法输出均为
UNVERIFIABLE；不会把导入时抛出的异常当作被测函数的期望异常。原始输出、退出状态、
超时标记和主进程比较记录分别保存。聚合与报告校验复用 M0；不采信子进程的 PASS。

候选、冻结用例、审批与运行报告分目录；M2 禁止把可信用例或证据置于候选仓库内。
默认运行证据放在候选仓库旁的 .coding-agent-evidence/运行ID。冻结文件和依赖环境
执行前后复核。目录分离和哈希检查不是 OS 权限隔离，不能防范同用户任意磁盘写、
竞态或篡改后恢复。POSIX 会清理子进程组；Windows 超时用 taskkill 清理进程树，
不声称能够阻止所有逃逸后代进程。

**运行标识只用于关联，不是认证。** 输出代码与候选同进程，候选仍可伪造一条合法
观测后正常退出。第 9 类分别记录格式拦截与单条伪造的已知误通过，不声称彻底防范。

本次演示和沙箱实测根目录为仓库外 D:\project\coding_agent_m2_runs
（WSL /mnt/d/project/coding_agent_m2_runs），运行使用独立子目录；通用代码由参数
接收路径，不把该位置作为唯一运行路径。真实 Executor 首次调用必须先由 MK
确认完整提示词与参数；默认请求 GPT-6 Luna medium，禁止 Astra 及跳过沙箱的选项。

本机 codex-cli 0.163.0 实测采用命名权限 m2_provider：仓库目录可写，
project_config.py 与 protected 只读，控制仓库和本次证据目录不可访问，命令网络禁用。
这不是单文件写白名单；未声明的新文件仍可创建，由 M1 快照事后检出。
单文件可写根配置在本机启动失败；传统 workspace-write 配置也未成功启动。
实测与 Executor 均加载本机配置并施加相同显式覆盖；配置文件及相关环境的哈希、
CLI 版本和权限模板须与实测证明一致，漂移时拒绝执行。实测只覆盖本次 Linux 后端，
不外推为 Windows 原生 Codex 沙箱已验证。

调用账本最多记录 10 次调用模型的 Codex exec 启动，失败启动与重试也占用次数；
纯版本、帮助和无模型 sandbox 命令不计入。一次 CLI 内部的多轮推理不是这里的计数单位。
默认 pytest 使用替身 Executor，不调用真实模型。prepare 只生成请求，execute 必须提供
已确认请求文件的 SHA-256，并复核任务、副本基线和完整请求未变化。
