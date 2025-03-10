import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings

load_dotenv()

BASE_DIR = Path(__file__).parent.parent


class RunConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000


class ApiV1Prefix(BaseModel):
    prefix: str = "/v1"
    auth: str = "/auth"


class ApiPrefix(BaseModel):
    prefix: str = "/api"
    v1: ApiV1Prefix = ApiV1Prefix()


class DatabaseConfig(BaseModel):
    url: PostgresDsn = PostgresDsn.build(
        scheme="postgresql+asyncpg",
        username=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
        host=os.getenv("POSTGRES_HOST"),
        port=int(os.getenv("POSTGRES_PORT")),
        path=os.getenv("POSTGRES_DB"),
    )
    echo: bool = False
    echo_pool: bool = False
    pool_size: int = 50
    max_overflow: int = 10

    naming_convention: dict[str, str] = {
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }


class RedisConfig(BaseModel):
    url: RedisDsn = RedisDsn.build(
        scheme="redis",
        host=os.getenv("REDIS_HOST"),
        port=int(os.getenv("REDIS_PORT")),
        path=os.getenv("REDIS_DB"),
        password=os.getenv("REDIS_PASSWORD"),
    )


class CORSConfig(BaseModel):
    allow_origins: list[str] = ["http://localhost:5173"]
    allow_credentials: bool = True
    allow_methods: list[str] = ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]
    allow_headers: list[str] = ["*"]
    expose_headers: list[str] = []


class AuthJWT(BaseModel):
    private_key_path: Path = BASE_DIR / "certs" / "jwt-private.pem"
    public_key_path: Path = BASE_DIR / "certs" / "jwt-public.pem"
    algorithm: str = "RS256"
    access_token_expire_minutes: int = 5
    refresh_token_expire_days: int = 30


class Settings(BaseSettings):
    run: RunConfig = RunConfig()
    api: ApiPrefix = ApiPrefix()
    db: DatabaseConfig = DatabaseConfig()
    redis: RedisConfig = RedisConfig()
    auth_jwt: AuthJWT = AuthJWT()
    cors: CORSConfig = CORSConfig()


settings = Settings()
