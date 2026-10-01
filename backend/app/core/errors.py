"""Service errors independent of HTTP and provider SDKs."""


class ApplicationError(Exception):
    code = "application_error"

    def __init__(self, message: str = "The operation could not be completed.") -> None:
        # Only client-safe messages belong here; chain the original exception.
        self.message = message
        super().__init__(message)


class ProviderUnavailableError(ApplicationError):
    code = "provider_unavailable"

    def __init__(self, message: str = "The requested provider is unavailable.") -> None:
        super().__init__(message)


class InvalidAudioError(ApplicationError):
    code = "invalid_audio"


class InvalidTextError(ApplicationError):
    code = "invalid_text"
