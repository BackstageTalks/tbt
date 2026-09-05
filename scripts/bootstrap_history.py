from __future__ import annotations


def main() -> None:
    raise SystemExit(
        "V20.7 safety stop: calendar-year bootstrap into Supabase is disabled. "
        "Use V20.7 archived-history backfill for GitHub, or restore_hot_buffer.py for the rolling Supabase buffer."
    )


if __name__ == "__main__":
    main()
