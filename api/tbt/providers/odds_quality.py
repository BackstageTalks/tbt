"""Shared conservative availability checks for provider odds."""


def odds_unavailable(row: dict) -> bool:
    """Missing flags retain legacy behavior; malformed explicit flags fail closed.

    A false flag on a child cannot reopen a suspended ancestor: callers must
    check each envelope before descending into its children.
    """
    return "suspended" in row and row["suspended"] is not False
