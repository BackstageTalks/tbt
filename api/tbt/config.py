from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "1" if default else "0") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    rapidapi_key: str = os.getenv("RAPIDAPI_KEY", "")
    rapidapi_host: str = os.getenv("RAPIDAPI_HOST", "tennisapi1.p.rapidapi.com")
    rapidapi_base_url: str = os.getenv("RAPIDAPI_BASE_URL", "https://tennisapi1.p.rapidapi.com").rstrip("/")
    request_timeout_seconds: int = 30
    firebase_project_id: str = os.getenv("FIREBASE_PROJECT_ID", "").strip()
    firebase_client_email: str = os.getenv("FIREBASE_CLIENT_EMAIL", "").strip()
    firebase_private_key: str = os.getenv("FIREBASE_PRIVATE_KEY", "")
    blinq_account_worker_token: str = os.getenv("BLINQ_ACCOUNT_WORKER_TOKEN", "").strip()
    blinq_smtp_host: str = os.getenv("BLINQ_SMTP_HOST", "").strip()
    blinq_smtp_port: int = _env_int("BLINQ_SMTP_PORT", 587)
    blinq_smtp_username: str = os.getenv("BLINQ_SMTP_USERNAME", "").strip()
    blinq_smtp_password: str = os.getenv("BLINQ_SMTP_PASSWORD", "")
    blinq_smtp_from: str = os.getenv("BLINQ_SMTP_FROM", "").strip()
    blinq_smtp_starttls: bool = _env_bool("BLINQ_SMTP_STARTTLS", True)
    blinq_public_url: str = os.getenv("BLINQ_PUBLIC_URL", "").strip().rstrip("/")
    blinq_admin_email: str = os.getenv("BLINQ_ADMIN_EMAIL", "").strip()
    model_artifact: str = str(Path(__file__).resolve().parents[1] / "artifacts/model.joblib")
    min_train_matches: int = 2500


settings = Settings()
