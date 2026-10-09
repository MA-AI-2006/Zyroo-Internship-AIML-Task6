"""User-facing exceptions so the UI never shows raw tracebacks."""


class DocFlowError(Exception):
    """Base error with a message that is safe to show to users."""

    code = "error"

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        if code:
            self.code = code


class FileValidationError(DocFlowError):
    code = "invalid_file"


class ExtractionError(DocFlowError):
    code = "unreadable"


class TransitionError(DocFlowError):
    code = "invalid_transition"


class NotFoundError(DocFlowError):
    code = "not_found"
