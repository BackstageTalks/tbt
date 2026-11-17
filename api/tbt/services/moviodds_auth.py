"""Backend-only MoviOdds API-key support; never log or embed secrets in URLs."""
import os


class MoviOddsAuthError(ValueError):
    """Provider key absent or invalid."""


class MoviOddsQuotaError(ValueError):
    """Provider throttled or exhausted account quota."""


def headers(user_agent: str, *, api_key: str | None = None) -> dict[str, str]:
    key = (api_key if api_key is not None else os.getenv("MOVIODDS_API_KEY", "")).strip()
    if not key:
        raise MoviOddsAuthError("moviodds_api_key_missing")
    if len(key) > 512 or any(ord(char) < 33 or ord(char) > 126 for char in key):
        raise MoviOddsAuthError("moviodds_api_key_invalid_format")
    return {"Accept": "application/json", "Accept-Encoding": "gzip",
            "User-Agent": user_agent, "X-API-Key": key}
