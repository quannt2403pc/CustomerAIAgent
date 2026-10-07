"""Cấu hình ứng dụng — đọc từ biến môi trường / `.env` (pydantic-settings).

Không giá trị mặc định nào ở đây là secret thật. `APP_ENCRYPTION_KEY` bắt buộc
phải do người triển khai cung cấp; thiếu nó thì `require_encryption_key()` báo lỗi
rõ ràng thay vì âm thầm lưu plaintext (plan.md §7.2, D1.5).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["antigravity", "google_api_key"]


class ConfigError(RuntimeError):
    """Cấu hình sai/thiếu — nên làm hệ thống dừng sớm, không chạy nửa vời."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Ứng dụng -----------------------------------------------------------
    app_env: str = "dev"
    log_level: str = "INFO"
    docs_enabled: bool = False
    tz: str = "Asia/Ho_Chi_Minh"
    cors_origins: str = "http://localhost:5173"

    # --- Luật thép L3 -------------------------------------------------------
    # Bản này không hiện thực đường gửi tin. Biến chỉ để tài liệu hoá ý định.
    dry_run: bool = True

    # --- Database -----------------------------------------------------------
    database_url: str = "postgresql+psycopg://appuser:change-me@localhost:5432/customeraiagent"
    run_migrations: bool = True

    # --- Mã hoá at-rest -----------------------------------------------------
    app_encryption_key: str = ""

    # --- Cổng A: CLIProxy / Antigravity ------------------------------------
    cliproxy_base_url: str = "http://localhost:8317"
    cliproxy_mgmt_key: str = ""
    cliproxy_auth_provider: str = "antigravity"

    # --- Cổng B: Google API Key --------------------------------------------
    google_api_base_url: str = "https://generativelanguage.googleapis.com"
    google_api_key: str = ""

    # --- Lựa chọn model (rỗng = chưa chọn; UI buộc chọn — plan.md §12.2) ----
    llm_provider: str = ""
    llm_model: str = ""
    llm_temperature: float = 0.9
    llm_max_output_tokens: int = 4096

    # --- Collector ----------------------------------------------------------
    # Cookie Facebook của **chính người vận hành** (task X.2). Rỗng = không
    # dùng. Đường chính là lưu mã hoá trong DB qua trang Cài đặt; biến môi
    # trường này chỉ để chạy CLI thuần.
    facebook_cookie: str = ""
    playwright_enabled: bool = False
    collector_timeout_seconds: float = 15.0
    collector_min_interval_seconds: float = 1.0
    screenshot_dir: str = "var/screenshots"
    upload_dir: str = "var/uploads"

    # --- Sinh nội dung ------------------------------------------------------
    rapport_message_count: int = Field(default=10, ge=5, le=10)
    max_regenerate_attempts: int = 2

    # --- Lịch 20h (APScheduler) --------------------------------------------
    scheduler_enabled: bool = True
    # Mốc cron của **job**. KHÔNG phải `trigger_time` trong output: field đó là
    # hằng số `"20:00"` do đề bài quy định và được `Literal` của Pydantic khoá
    # lại (app/schemas/output.py), nên hai thứ không thể lệch nhau trong JSON
    # nộp bài. Hai biến dưới đây chỉ để **kiểm chứng** lịch chạy thật mà không
    # phải chờ tới 20h (task.md D2.4 DoD) — triển khai thật thì để nguyên 20:00.
    evening_cron_hour: int = Field(default=20, ge=0, le=23)
    evening_cron_minute: int = Field(default=0, ge=0, le=59)
    # Số profile tối đa mỗi lượt 20h. Mỗi hook là 2–6 lượt gọi model (sinh +
    # judge + sinh lại), nên 50 profile có thể thành 300 lượt gọi trong một phút
    # → chạm hạn mức nhà cung cấp (task.md I-25). Chặn trần có chủ đích.
    evening_max_profiles: int = Field(default=20, ge=1, le=200)

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, v: str) -> str:
        level = v.upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"LOG_LEVEL không hợp lệ: {v}")
        return level

    @field_validator("llm_provider")
    @classmethod
    def _check_provider(cls, v: str) -> str:
        if v and v not in {"antigravity", "google_api_key"}:
            raise ValueError(
                f"LLM_PROVIDER không hợp lệ: {v!r}. "
                "Chỉ nhận 'antigravity', 'google_api_key', hoặc rỗng (chưa chọn)."
            )
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def sync_database_url(self) -> str:
        """URL đồng bộ cho Alembic và jobstore APScheduler."""
        return self.database_url.replace("+psycopg_async", "+psycopg").replace(
            "postgresql+asyncpg", "postgresql+psycopg"
        )

    def require_encryption_key(self) -> str:
        """Trả `APP_ENCRYPTION_KEY`, hoặc nổ nếu thiếu — không bao giờ fallback plaintext."""
        key = self.app_encryption_key.strip()
        if not key or key == "SINH-NGAU-NHIEN":
            raise ConfigError(
                "Thiếu APP_ENCRYPTION_KEY. Sinh khoá bằng:\n"
                '  python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"\n'
                "rồi điền vào .env. Hệ thống KHÔNG lưu secret dạng plaintext."
            )
        return key

    def require_cliproxy_mgmt_key(self) -> str:
        key = self.cliproxy_mgmt_key.strip()
        if not key or key == "SINH-NGAU-NHIEN":
            raise ConfigError(
                "Thiếu CLIPROXY_MGMT_KEY. Khoá này phải TRÙNG với "
                "remote-management.secret-key trong cliproxy/config.yaml. "
                "Để rỗng thì route quản trị của CLIProxy trả 404 (bẫy B4)."
            )
        return key


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
