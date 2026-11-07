from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ENVIRONMENT: str = "development"
    APP_NAME: str = "ProcureMind API"
    API_V1_STR: str = "/api/v1"
    DEBUG: bool = True

    # Strict CORS configuration
    CORS_ORIGINS: str | list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [i.strip() for i in v.split(",") if i.strip()]
        elif isinstance(v, list):
            return v
        return []

    # Database
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/procuremind_dev"

    # Storage Interface Configuration
    STORAGE_BACKEND: str = "local"  # 'local' or 's3'
    LOCAL_STORAGE_DIR: str = "./local_storage"
    S3_BUCKET_NAME: str = "procuremind-private-docs"
    S3_REGION: str = "us-east-1"
    S3_ENDPOINT_URL: str | None = None
    S3_ACCESS_KEY_ID: str | None = None
    S3_SECRET_ACCESS_KEY: str | None = None

    # Upload Limits & Short-Lived URL Security
    MAX_UPLOAD_SIZE_BYTES: int = 15 * 1024 * 1024  # 15 MB
    ALLOWED_FILE_EXTENSIONS: set[str] = {"pdf", "xlsx", "csv", "png", "jpg", "jpeg"}
    DOWNLOAD_URL_EXPIRES_SECONDS: int = 300  # 5 minutes
    STORAGE_SIGNING_SECRET: str | None = None

    # Secondary Integrations (Optional)
    FALKORDB_ENABLED: bool = False
    FALKORDB_HOST: str = "localhost"
    FALKORDB_PORT: int = 6379

    CHROMA_ENABLED: bool = False
    CHROMA_HOST: str = "localhost"
    CHROMA_PORT: int = 8000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
