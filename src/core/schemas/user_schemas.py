from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator
from pydantic_core.core_schema import ValidationInfo


class UserBase(BaseModel):
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    username: str


class UserCreate(UserBase):
    password: str


class UserSchema(UserBase):
    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserRegister(UserBase):
    password: str
    confirm_password: str

    @field_validator("confirm_password")
    def verify_password_match(
        cls, v: str, values: ValidationInfo, **kwargs: object
    ) -> str:
        password = values.data.get("password")

        if v != password:
            raise ValueError("The two passwords did not match.")

        return v


class UserLogin(BaseModel):
    username: str
    password: str


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None


# class PasswordResetSchema(BaseModel):
#     password: str
#     confirm_password: str
#
#     @field_validator("confirm_password")
#     def verify_password_match(cls, v, values, **kwargs: Any) -> str:
#         password = values.get("password")
#
#         if v != password:
#             raise ValueError("The two passwords did not match.")
#
#         return v
#
#
# class PasswordUpdateSchema(PasswordResetSchema):
#     old_password: str


# class OldPasswordErrorSchema(BaseModel):
#     old_password: bool
#
#     @field_validator("old_password")
#     def check_old_password_status(cls, v, values, **kwargs):
#         if not v:
#             raise ValueError("Old password is not correct")
