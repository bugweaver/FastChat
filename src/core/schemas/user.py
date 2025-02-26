from pydantic import BaseModel, EmailStr, ConfigDict


class UserSchema(BaseModel):
    username: str
    password: bytes
    email: EmailStr | None = None
    active: bool = True

    model_config = ConfigDict(strict=True)