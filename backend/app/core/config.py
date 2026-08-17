import os
import secrets
import logging

logger = logging.getLogger("stratroom.config")


class Settings:
    # ── Application ──
    APP_VERSION: str = os.getenv("APP_VERSION", "1.0.0")
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    DEBUG: bool = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_JSON_MODE: bool = os.getenv("LOG_JSON_MODE", "false").lower() in ("true", "1", "yes")
    ENABLE_DOCS: bool = os.getenv("ENABLE_DOCS", "true").lower() in ("true", "1", "yes")

    # ── Database ──
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://stratroom:stratroom_pw@db:5432/stratroom"
    )
    DB_POOL_SIZE: int = int(os.getenv("DB_POOL_SIZE", "10"))
    DB_MAX_OVERFLOW: int = int(os.getenv("DB_MAX_OVERFLOW", "20"))
    DB_POOL_TIMEOUT: int = int(os.getenv("DB_POOL_TIMEOUT", "30"))
    DB_POOL_RECYCLE: int = int(os.getenv("DB_POOL_RECYCLE", "1800"))
    DB_POOL_PRE_PING: bool = os.getenv("DB_POOL_PRE_PING", "true").lower() in ("true", "1", "yes")

    # ── Authentication ──
    JWT_SECRET: str = os.getenv("JWT_SECRET", "")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

    # ── CORS ──
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173,http://localhost:8001")

    # ── Security ──
    MIN_PASSWORD_LENGTH: int = 8
    MAX_LOGIN_ATTEMPTS: int = 10
    LOGIN_RATE_LIMIT_WINDOW: int = 60

    # ── Uploads ──
    MAX_UPLOAD_FILES: int = 10
    MAX_UPLOAD_SIZE_MB: int = 5
    MAX_STRING_LENGTH: int = 10000
    MAX_PROMPT_LENGTH: int = 50000

    # ── AI Token / I/O limits (Task 2: token optimization) ──
    # Inbound chat message character cap (prevents token-input spikes).
    MAX_CHAT_INPUT_CHARS: int = int(os.getenv("MAX_CHAT_INPUT_CHARS", "8000"))
    # Hard output cap applied to every LLM response (global guard).
    MAX_RESPONSE_CHARS: int = int(os.getenv("MAX_RESPONSE_CHARS", "16000"))
    # Per-call provider max_tokens ceiling (advisory; actual char cap is above).
    MAX_LLM_MAX_TOKENS: int = int(os.getenv("MAX_LLM_MAX_TOKENS", "2048"))
    # Restrict tool-result summaries fed back to the model on subsequent turns.
    MAX_TOOL_RESULT_CHARS: int = int(os.getenv("MAX_TOOL_RESULT_CHARS", "4000"))
    # Rolling window of responses kept for the in-memory token benchmark.
    TOKEN_BENCHMARK_WINDOW: int = int(os.getenv("TOKEN_BENCHMARK_WINDOW", "200"))

    # ── MySQL (Java business data) ──
    MYSQL_HOST: str = os.getenv("MYSQL_HOST", "host.docker.internal")
    MYSQL_PORT: int = int(os.getenv("MYSQL_PORT", "3306"))
    MYSQL_USER: str = os.getenv("MYSQL_USER", "root")
    MYSQL_PASSWORD: str = os.getenv("MYSQL_PASSWORD", "Admin#123")
    MYSQL_DATABASE: str = os.getenv("MYSQL_DATABASE", "orgstructure")

    # ── Java Service Bridge (legacy, kept for scorecard HTTP calls) ──
    JAVA_AUTH_URL: str = os.getenv("JAVA_AUTH_URL", "http://host.docker.internal:9010")
    JAVA_DB_URL: str = os.getenv("JAVA_DB_URL", "http://host.docker.internal:9040")
    JAVA_USER_URL: str = os.getenv("JAVA_USER_URL", "http://host.docker.internal:9050")
    JAVA_SCORECARD_URL: str = os.getenv("JAVA_SCORECARD_URL", "http://host.docker.internal:9060")

    # ── Rate Limiting ──
    RATE_LIMIT_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "120"))
    RATE_LIMIT_AI_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_AI_PER_MINUTE", "30"))

    # ── AI Providers ──
    ALLOWED_PROVIDERS: frozenset[str] = frozenset({
        "openai", "anthropic", "google", "deepseek", "moonshot",
        "together", "mistral", "xai", "ollama", "mock", "qwen", "qwen2.5",
    })

    # Server-side default LLM config — used when a request supplies no
    # api_key/endpoint of its own, so agents work out of the box.
    AI_DEFAULT_PROVIDER: str = os.getenv("AI_PROVIDER", "").strip().lower()
    AI_DEFAULT_API_KEY: str = os.getenv("AI_API_KEY", "").strip()
    AI_DEFAULT_MODEL: str = os.getenv("AI_MODEL", "").strip()

    # ── Storage ──
    STORAGE_DIR: str = os.getenv("STORAGE_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "storage"))

    def __init__(self):
        if not self.JWT_SECRET:
            self.JWT_SECRET = secrets.token_hex(32)
            logger.warning(
                "JWT_SECRET not set — generated ephemeral key. "
                "Tokens will NOT survive restarts. Set JWT_SECRET in environment for production."
            )
        elif self.JWT_SECRET in ("dev_only_secret", "change_this_super_secret_key", ""):
            logger.warning(
                "JWT_SECRET is using an insecure default value. "
                "Set a strong, unique JWT_SECRET in your environment."
            )
        if self.JWT_ALGORITHM not in ("HS256", "HS384", "HS512"):
            raise ValueError(f"Invalid JWT_ALGORITHM: {self.JWT_ALGORITHM}")
        if self.AI_DEFAULT_PROVIDER and self.AI_DEFAULT_PROVIDER not in self.ALLOWED_PROVIDERS:
            raise ValueError(
                f"AI_PROVIDER '{self.AI_DEFAULT_PROVIDER}' is not in ALLOWED_PROVIDERS: "
                f"{', '.join(sorted(self.ALLOWED_PROVIDERS))}"
            )

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"


settings = Settings()
