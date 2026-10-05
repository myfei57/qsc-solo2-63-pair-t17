"""Exception hierarchy shared by every subsystem."""

from __future__ import annotations


class ControlError(Exception):
    """Base class for every error raised by the control service."""

    code = "control_error"

    def as_dict(self) -> dict[str, str]:
        return {"error": str(self), "code": self.code}


class ValidationError(ControlError):
    """An entity or payload failed a structural check."""

    code = "validation_error"


class NotFoundError(ControlError):
    """A requested entity does not exist."""

    code = "not_found"


class ConflictError(ControlError):
    """The request contradicts the committed state."""

    code = "conflict"


class OrderingError(ControlError):
    """A step was attempted out of the order the plant allows."""

    code = "ordering_error"


class StaleError(ControlError):
    """A generation, watermark or schedule reference is out of date."""

    code = "stale_reference"


class QuotaError(ControlError):
    """A quota or capacity bound rejected the request."""

    code = "quota_exceeded"
