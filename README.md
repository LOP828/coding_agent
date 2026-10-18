# Coding Agent M0.2

独立仓库中的 M0.2 数据契约、结构准入与确定性策略汇总。
`src/coding_agent/m0.py` 直接迁移自规格包的 `checks/spec_reference.py`，
仅整理模块导入、Schema 资源与测试清单根目录；没有第二套规则引擎。

## 安装与验收

需要 Python 3.11+。依赖全部安装到虚拟环境：运行依赖为
`jsonschema==4.26.0`，开发依赖为 `pytest==9.0.2`，与规格包版本一致。

Windows PowerShell，在本仓库根目录运行：

```powershell
python.exe -m venv .venv-windows
.\.venv-windows\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Remove-Item Env:PYTHONUTF8 -ErrorAction SilentlyContinue
python -m pytest
```

Linux，在本仓库根目录运行：

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest
```

环境缺少 ensurepip 时可用 `uv venv .venv` 创建虚拟环境，再用
`uv pip install --python .venv/bin/python -e '.[dev]'` 安装。
平台专用路径只出现在对应平台的安装示例中；实现不依赖这些路径。
统一验收命令为 `python -m pytest`，无需另外运行规格包自检。

## 目录和测试收集

- `src/coding_agent/m0.py`：正式策略实现。
- `src/coding_agent/schemas/`：三个原样复制的版本化 Schema，也是安装包资源。
- `tests/test_spec_regressions.py`：迁移的既有规则回归，直接导入正式模块。
- `tests/test_migration_integration.py`：资源根目录分离与准入调用边界。
- `tests/test_sample_execution.py`：四个已知候选及独立原文 oracle 的实跑检查。
- `tests/data/m0/`：原样复制的夹具、候选代码和冻结验收测试。
- `tests/support/sample_diagnostics.py`：由原自检脚本提取的已知样本执行工具。
- `audit_evidence/`：按平台保存的本仓库实跑日志、JUnit XML 和摘要。

`pyproject.toml` 仅显式排除 `tests/data` 的默认收集，不设置缩小范围的
`testpaths`，不复制规格包的 `pytest.ini`。`tests/data` 是被测样本数据，
其中 `test_*.py` 只能由集成测试在各自的临时候选环境中运行；它们包含
故意失败的候选与错误契约，不能直接当成正式主线单测。
这些预期失败的退出码和失败数量由默认集成测试明确断言，不使用 skip 或 xfail。

正式运行和测试不读取 `docs/`。该目录中的原始交接压缩包只作只读参考。
任务卡内 `tests_reference/...`、`tests_wrong_contract/...` 及 manifest、
原文和审批摘要保持不变；路径相对 `tests/data/m0/` 解析。

## 最小接口

```python
from pathlib import Path
from coding_agent.m0 import (
    aggregate_gate, read_json, validate_admission, validate_report,
)

test_root = Path("tests/data/m0")
task = read_json(test_root / "fixtures/01_correct/atomic_task.json")
source = read_json(test_root / "fixtures/source_requirements.json")
trusted_records = read_json(test_root / "fixtures/trusted_review_records.json")
validate_admission(task, source, trusted_records, test_root, fixture_mode=True)
report = read_json(test_root / "fixtures/01_correct/verification_report_expected.json")
computed = aggregate_gate(task, report["results"], report["changed_paths"])
validate_report(task, report, expected_revision="synthetic-01")
```

`validate_admission(..., test_root, *, schema_root=None, fixture_mode=False)`
将测试清单根目录与 Schema 根目录分开。Schema 默认经 `importlib.resources`
从 `coding_agent/schemas` 加载；如显式提供 `schema_root`，该目录直接包含
三个 Schema 文件。`validate_schema(name, data, *, schema_root=None)` 和
`validate_report(..., expected_revision=..., schema_root=None)` 不依赖测试根目录。
本地相对路径写入逻辑数据时应使用 `Path.as_posix()`；策略采用自己的 POSIX
字符串匹配，不使用宿主 glob。

调用方必须先完成准入，再执行后续操作。`validate_report` 不代替准入。
报告中的 gate 只用于与重算结果比对；如需保留不一致时的真实 gate，先调用
`aggregate_gate` 并保存结果。M1 必须从控制侧提供批准记录、代码 revision、
真实检查结果与 changed_paths，不能信任候选代码自报的数据。

## 固定边界

M0 实现 Schema、来源/哈希、结构覆盖、授权与批准绑定、测试 manifest、
路径策略、报告身份及必需检查验证。不执行未知候选、不接 AI API，
不实现 Executor、计划生成、调度、真实 Git 变更采集或语义审查。

样本 gate 必须保持：01 为 PASS；02、03 为 HARD_FAIL / EXECUTION_FAIL；
04 为 PASS / NONE。04 的独立原文 oracle 仍为 1 passed、1 failed、退出码 1，
评测标签为 `FALSE_PASS_EXPECTED_KNOWN_GAP`，oracle 不进入已批准任务的 gate。

临时目录不是沙箱；审批 JSON 是模拟可信控制记录，hash 不是签名；
changed_paths 和期望报告是合成输入。M1 尚需真实 Runner、证据采集和权限隔离，
隔离本身无法纠正场景 04 的错误契约；M2 尚缺独立语义审查，不能承诺检测成功。
测试数量不代表生产拦截率。Windows 原生与 Linux/WSL 的验收结果分别记录，
最终数字见 `VALIDATION.md`。
