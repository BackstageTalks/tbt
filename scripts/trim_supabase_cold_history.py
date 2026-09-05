from __future__ import annotations


def main() -> None:
    raise SystemExit(
        "V20.7 safety stop: fixed-year Supabase trimming is retired. "
        "Use scripts/trim_supabase_hot_buffer.py with rolling retention instead."
    )


if __name__ == "__main__":
    main()
