from fastapi import Form
from fastapi.security import OAuth2PasswordRequestForm


class CustomOAuth2PasswordRequestForm(OAuth2PasswordRequestForm):
    """
    Custom OAuth2 password request form.

    This form is a simplified version of the standard OAuth2PasswordRequestForm.
    It removes unnecessary fields such as `grant_type`, `scope`, `client_id`,
    and `client_secret`, leaving only `username` and `password`.

    Args:
        username (str): The username of the user.
        password (str): The user's password.
    """
    def __init__(
        self,
        username: str = Form(...),
        password: str = Form(...),
    ) -> None:
        # Убираем grant_type, scope, client_id и client_secret
        super().__init__(
            grant_type=None,
            username=username,
            password=password,
            scope="",
            client_id=None,
            client_secret=None,
        )
