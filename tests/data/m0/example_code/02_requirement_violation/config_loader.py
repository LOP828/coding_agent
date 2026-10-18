class MissingProviderError(ValueError):
    pass


def validate_config(config: dict) -> dict:
    # 错误：违反 R-001，静默填入默认 provider。
    return {"provider": "local", **config}
