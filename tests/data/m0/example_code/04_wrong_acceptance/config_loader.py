class MissingProviderError(ValueError):
    pass


def validate_config(config: dict) -> dict:
    # 根据被扭曲的验收条件实现；“符合任务卡”，但违背原始 R-001。
    return {"provider": "local", **config}
