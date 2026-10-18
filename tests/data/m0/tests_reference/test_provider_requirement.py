# M1 中应由可信验证进程注入；不得由 Executor 修改。
# 此文件演示原始需求 R-001 对应的基准测试。
import pytest
from config_loader import MissingProviderError, validate_config


def test_missing_provider_raises():
    with pytest.raises(MissingProviderError):
        validate_config({})


def test_present_provider_unchanged():
    assert validate_config({"provider": "openai"}) == {"provider": "openai"}
