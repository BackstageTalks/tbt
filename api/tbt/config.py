from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    rapidapi_key: str = os.getenv("RAPIDAPI_KEY", "")
    rapidapi_host: str = os.getenv("RAPIDAPI_HOST", "tennisapi1.p.rapidapi.com")
    rapidapi_base_url: str = os.getenv("RAPIDAPI_BASE_URL", "https://tennisapi1.p.rapidapi.com").rstrip("/")
    request_timeout_seconds: int = 30
    supabase_url: str = os.getenv("SUPABASE_URL", "").rstrip("/")
    supabase_anon_key: str = os.getenv("SUPABASE_ANON_KEY", "")
    supabase_service_role_key: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    blinq_admin_emails: str = os.getenv("BLINQ_ADMIN_EMAILS", "")
    model_artifact: str = str(Path(__file__).resolve().parents[1] / "artifacts/model.joblib")
    min_train_matches: int = 2500


settings = Settings()
