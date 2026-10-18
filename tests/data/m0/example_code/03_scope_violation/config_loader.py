class MissingProviderError(ValueError):
    pass


def validate_config(config: dict) -> dict:
    if "provider" not in config:
        raise MissingProviderError("provider is required")
    return config
