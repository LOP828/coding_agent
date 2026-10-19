class MissingProviderError(ValueError):
    pass


def validate_config(config):
    raise NotImplementedError("Implement provider validation")
