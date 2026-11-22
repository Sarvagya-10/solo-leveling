"""Domain exceptions. Their messages are safe to show to the user."""


class ShogunError(Exception):
    """Base class for expected, user-facing errors."""


class ValidationError(ShogunError):
    """Input failed validation."""


class NotFoundError(ShogunError):
    """A referenced record does not exist."""


class ConflictError(ShogunError):
    """Operation conflicts with current state (e.g. completing a revision twice)."""
