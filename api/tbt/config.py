from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    rapidapi_key: str = os.getenv("RAPIDAPI_KEY", "")
    rapidapi_host: str = os.getenv(
        "RAPIDAPI_HOST", "tennis-api-atp-wta-itf.p.rapidapi.com"
    )
    rapidapi_base_url: str = os.getenv(
        "RAPIDAPI_BASE_URL", "https://tennis-api-atp-wta-itf.p.rapidapi.com"
    ).rstrip("/")

    supabase_url: str = os.getenv("SUPABASE_URL", "").rstrip("/")
    supabase_anon_key: str = os.getenv("SUPABASE_ANON_KEY", "")
    supabase_service_role_key: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    allow_anon_writes: bool = _bool_env("TBT_ALLOW_ANON_WRITES", False)

    telegram_bot_token: str = os.getenv("TGBOT", "")
    telegram_chat_id: str = os.getenv("TGCHID", "")
    admin_api_key: str = os.getenv("TBT_ADMIN_API_KEY", "")

    model_artifact: str = os.getenv(
        "TBT_MODEL_ARTIFACT",
        str(Path(__file__).resolve().parents[1] / "artifacts" / "model.joblib"),
    )
    history_start_year: int = _int_env("TBT_HISTORY_START_YEAR", 2018)
    prediction_horizon_days: int = _int_env("TBT_PREDICTION_HORIZON_DAYS", 3)
    min_train_matches: int = _int_env("TBT_MIN_TRAIN_MATCHES", 2500)
    request_timeout_seconds: int = _int_env("TBT_REQUEST_TIMEOUT_SECONDS", 30)
    log_level: str = os.getenv("TBT_LOG_LEVEL", "INFO").upper()
    cors_origins: str = os.getenv("TBT_CORS_ORIGINS", "*")

    @property
    def supabase_write_key(self) -> str:
        if self.supabase_service_role_key:
            return self.supabase_service_role_key
        if self.allow_anon_writes:
            return self.supabase_anon_key
        return ""


settings = Settings()
