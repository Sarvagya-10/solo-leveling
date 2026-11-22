"""AI-layer exceptions. Messages are safe to display (never contain keys)."""


class AIError(Exception):
    """Base class for AI provider errors."""


class AINotConfiguredError(AIError):
    """Missing API key or model configuration."""


class AIAuthError(AIError):
    """The provider rejected the credentials."""


class AIRateLimitError(AIError):
    """Rate limit or quota exceeded after retries."""


class AIUnavailableError(AIError):
    """Network failure, timeout or provider outage."""


class AIResponseError(AIError):
    """The provider answered, but the output was unusable (invalid JSON/schema)."""
