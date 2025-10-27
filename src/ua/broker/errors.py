class UpbitError(Exception):
    pass


class AuthenticationError(UpbitError):
    pass


class PermissionError(UpbitError):
    pass


class RateLimitError(UpbitError):
    pass


class InvalidRequestError(UpbitError):
    pass


class NotFoundError(UpbitError):
    pass


class ExchangeError(UpbitError):
    pass

