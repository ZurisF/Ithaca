"""Application errors translated to HTTP responses at the router boundary."""


class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str, retryable: bool = False):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(message)
