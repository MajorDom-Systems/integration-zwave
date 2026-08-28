class ZwaveConnectionError(Exception):
    """Raised when Matter client is not started or not available."""


class ZwaveUnexpectedError(Exception):
    """Raised when an unexpected internal error occurs."""
