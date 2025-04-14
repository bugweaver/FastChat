from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from pydantic_core.core_schema import ValidationInfo


class UserBase(BaseModel):
    email: EmailStr
    first_name: str | None = Field(None, min_length=2, max_length=50)
    last_name: str | None = Field(None, min_length=2, max_length=50)
    username: str = Field(..., min_length=3, max_length=30, pattern=r"^[a-zA-Z0-9_]+$")

    @field_validator("username")
    def validate_username(cls, v: str) -> str:
        forbidden_words = {"admin", "root", "superuser"}
        if v.lower() in forbidden_words:
            raise ValueError("This username is not allowed")
        return v


class UserCreate(UserBase):
    password: str = Field(..., min_length=8, max_length=100)

    @field_validator("password")
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class UserSchema(UserBase):
    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": 1,
                "email": "user@example.com",
                "username": "john_doe",
                "is_active": True,
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00",
            }
        },
    )


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
    username: str = Field(..., min_length=3, max_length=30)
    password: str = Field(..., min_length=8, max_length=100)


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    first_name: str | None = Field(None, min_length=2, max_length=50)
    last_name: str | None = Field(None, min_length=2, max_length=50)
    username: str | None = Field(
        None, min_length=3, max_length=30, pattern=r"^[a-zA-Z0-9_]+$"
    )

    @field_validator("email")
    def validate_email_domain(cls, v: str | None) -> str | None:
        if v and "example.com" in v:
            raise ValueError("This email domain is not allowed")
        return v


class UserStatus(BaseModel):
    """User Status Model"""

    user_id: int | str
    status: bool

    @field_validator("user_id")
    @classmethod
    def convert_user_id_to_str(cls, v: str) -> str:
        return v


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
