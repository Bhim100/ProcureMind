from urllib.parse import urlparse

from pydantic import ValidationInfo, field_validator
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

    # PayPal Sandbox Configuration (Strictly Sandbox - Live is prohibited)
    PAYPAL_ENVIRONMENT: str = "sandbox"
    PAYPAL_BASE_URL: str = "https://api-m.sandbox.paypal.com"
    PAYPAL_CLIENT_ID: str = ""
    PAYPAL_CLIENT_SECRET: str = ""
    PAYPAL_WEBHOOK_ID: str = ""

    # Auditor Secret for Invoice Approvals (No default; must be configured with >= 16 chars)
    AUDITOR_API_KEY: str | None = None

    # Phase 6: AI Explanation Service Configuration
    LLM_PROVIDER: str = "gemini"
    LLM_API_KEY: str | None = None
    LLM_MODEL: str = "gemini-3.8-flash"
    LLM_BASE_URL: str | None = None
    LLM_TIMEOUT_SECONDS: int = 15

    @field_validator("PAYPAL_ENVIRONMENT")
    @classmethod
    def validate_paypal_environment(cls, v: str) -> str:
        clean = v.strip().lower()
        if clean != "sandbox":
            raise ValueError(
                f"ProcureMind is strictly restricted to PayPal Sandbox. "
                f"PAYPAL_ENVIRONMENT must be 'sandbox', received: '{v}'"
            )
        return clean

    @field_validator("PAYPAL_BASE_URL")
    @classmethod
    def validate_paypal_sandbox_url(cls, v: str, info: ValidationInfo) -> str:
        clean_url = v.strip()
        parsed = urlparse(clean_url)

        # Allow localhost / testserver strictly in test environments
        env = info.data.get("ENVIRONMENT", "development")
        if env == "test" and parsed.hostname in ("localhost", "127.0.0.1", "testserver"):
            return clean_url

        if parsed.scheme != "https":
            raise ValueError(f"PayPal Sandbox URL scheme must be 'https', got '{parsed.scheme}'")

        allowed_hostnames = {"api-m.sandbox.paypal.com", "api.sandbox.paypal.com"}
        if parsed.hostname not in allowed_hostnames:
            raise ValueError(
                f"Invalid PayPal Sandbox URL: '{clean_url}'. Hostname '{parsed.hostname}' is unauthorized. "
                f"Permitted hostnames: {allowed_hostnames}. Live endpoints and subdomains are strictly prohibited."
            )

        # Prohibit path segments, query parameters, fragments, userinfo, and custom ports
        if parsed.path not in ("", "/"):
            raise ValueError(f"PayPal Sandbox URL must not include subpaths: '{parsed.path}'")
        if parsed.query:
            raise ValueError("PayPal Sandbox URL must not include query strings")
        if parsed.fragment:
            raise ValueError("PayPal Sandbox URL must not include fragments")
        if parsed.username or parsed.password:
            raise ValueError("PayPal Sandbox URL must not include user credentials")
        if parsed.port not in (None, 443):
            raise ValueError(
                f"PayPal Sandbox URL must use standard HTTPS port (got port {parsed.port})"
            )

        return f"https://{parsed.hostname}"

    @field_validator("AUDITOR_API_KEY")
    @classmethod
    def validate_auditor_api_key(cls, v: str | None) -> str | None:
        if v is not None:
            clean = v.strip()
            if len(clean) < 16:
                raise ValueError(
                    "AUDITOR_API_KEY must be at least 16 characters long for security."
                )
            if clean in ("pm-dev-auditor-key-secret", "secret", "password", "1234567890123456"):
                raise ValueError("Insecure default or trivial AUDITOR_API_KEY is prohibited.")
            return clean
        return None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
