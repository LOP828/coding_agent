class MissingProviderError(ValueError):
    """缺少 provider 字段。"""


def validate_config(config: dict) -> dict:
    if "provider" not in config:
        raise MissingProviderError("provider is required")
    return config
