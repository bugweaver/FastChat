from fastapi import HTTPException, status


class MissingUsernameError(ValueError):
    def __init__(self, message: str = "Username is missing") -> None:
        self.message = message
        super().__init__(self.message)


class CredentialsException(HTTPException):
    def __init__(
        self,
        detail: str = "Could not validate credentials",
        headers: dict = None,
    ) -> None:
        if headers is None:
            headers = {"WWW-Authenticate": "Bearer"}
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers=headers,
        )
