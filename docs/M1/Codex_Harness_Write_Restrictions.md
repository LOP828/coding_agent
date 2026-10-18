# Codex harness 可写路径限制调查（R-M1-07）

调查日期：2026-10-18。对象为开源 [openai/codex](https://github.com/openai/codex)，选定发布标签 `rust-v0.114.0`，实际提交 **`b9904c0ae4ecb773549efd6ea3fb05229402fdb9`**；不是“最新版本”结论。已联网运行 `git ls-remote` 核实标签及解引用提交，并读取该提交源码。仅源码/文档调查，未接入 harness，也未运行其跨平台隔离验收。

**结论：目录级写入限制有实现；文件级路径权限也有配置及后端实现，但不能据此承诺任意单文件白名单在所有执行路径、平台均生效。**

传统配置示例（路径仅为示例，使用时替换为本机绝对路径）：

```toml
sandbox_mode = "workspace-write"
approval_policy = "never"
[sandbox_workspace_write]
writable_roots = ["/work/extra-output"]
exclude_slash_tmp = true
exclude_tmpdir_env_var = true
network_access = false
```

`writable_roots` 是额外可写根，不是把当前工作区缩小到这些路径。实现仍加入 cwd；默认临时目录可以由上述两个开关排除。`.git`、`.agents`、`.codex` 存在时有默认只读子路径处理。依据：[固定提交的 SandboxPolicy 实现](https://github.com/openai/codex/blob/b9904c0ae4ecb773549efd6ea3fb05229402fdb9/codex-rs/protocol/src/protocol.rs#L866)、[配置类型](https://github.com/openai/codex/blob/b9904c0ae4ecb773549efd6ea3fb05229402fdb9/codex-rs/core/src/config/types.rs#L810)。官方配置入口可交叉参考，但不能用滚动文档替代版本依据：[Configuration Reference](https://learn.chatgpt.com/docs/config-file/config-reference)。

该版本另有命名权限配置，支持绝对路径的 `read`、`write`、`none`。例如下面表达“工作区可写，但一个文件只读”的配置；这是源码支持的配置表达，不是本次实跑证明：

```toml
default_permissions = "task"
[permissions.task.filesystem]
":root" = "read"
"/work/repo" = "write"
"/work/repo/project_config.py" = "read"
```

解析器不把路径限定为目录；更窄的非写权限作为可写根的排除项。Linux bubblewrap 实现先只读绑定，再为可写路径绑定，最后恢复只读子路径；macOS Seatbelt 也生成路径约束。依据：[配置解析](https://github.com/openai/codex/blob/b9904c0ae4ecb773549efd6ea3fb05229402fdb9/codex-rs/core/src/config/permissions.rs#L159)、[细粒度权限](https://github.com/openai/codex/blob/b9904c0ae4ecb773549efd6ea3fb05229402fdb9/codex-rs/protocol/src/permissions.rs#L283)、[Linux 文件系统绑定](https://github.com/openai/codex/blob/b9904c0ae4ecb773549efd6ea3fb05229402fdb9/codex-rs/linux-sandbox/src/bwrap.rs#L180)、[Seatbelt](https://github.com/openai/codex/blob/b9904c0ae4ecb773549efd6ea3fb05229402fdb9/codex-rs/core/src/seatbelt.rs#L354)。

**生效边界：**旧策略转换在工作区根不可写、仅指定其他可写路径时会报错；旧 Linux Landlock 路径也有限制。因此“整个仓库只读、仅一个业务文件可写”不能仅凭配置格式认定已端到端支持。应在 M2 对选定版本、实际后端、已有/新建文件、重命名替换、链接和越权子进程分别实测。依据：[legacy 转换限制](https://github.com/openai/codex/blob/b9904c0ae4ecb773549efd6ea3fb05229402fdb9/codex-rs/protocol/src/permissions.rs#L350)、[Linux 后端边界](https://github.com/openai/codex/blob/b9904c0ae4ecb773549efd6ea3fb05229402fdb9/codex-rs/linux-sandbox/src/landlock.rs#L40)。

工具层检查只能限制经过工具的操作；OS 后端限制被沙箱启动的进程及其子进程，不能等同于提示词约束。是否选择后端、平台配置、额外授权和不经沙箱的执行路径都会改变边界；Windows 原生路径需单独验证。[执行路径选择与转换源码](https://github.com/openai/codex/blob/b9904c0ae4ecb773549efd6ea3fb05229402fdb9/codex-rs/core/src/sandboxing/mod.rs#L515)。本调查不把这些能力归为 M1 已实现防护。
