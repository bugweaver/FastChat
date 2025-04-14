import factory

from core.auth.utils.password_utils import hash_password
from core.models import User
from core.schemas.user_schemas import UserRegister

from .base import AsyncSQLAlchemyModelFactory


class UserFactory(AsyncSQLAlchemyModelFactory):
    """Factory for creating test users."""

    class Meta:
        model = User
        sqlalchemy_session = None
        sqlalchemy_session_persistence = None

    email = factory.Faker("email")
    username = factory.Faker("user_name")
    password = factory.LazyAttribute(
        lambda o: hash_password("testpassword").decode("utf-8")
    )
    is_active = True

    @classmethod
    async def build_async(cls, **kwargs) -> User:
        """Creates a User instance with dynamic keyword arguments."""
        return cls._meta.model(**kwargs)


class UserRegisterFactory(factory.Factory):
    """Factory for creating user registration schemes."""

    class Meta:
        model = UserRegister

    email = factory.Faker("email")
    username = factory.Faker("user_name")
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    password = "testpassword"
    confirm_password = "testpassword"
