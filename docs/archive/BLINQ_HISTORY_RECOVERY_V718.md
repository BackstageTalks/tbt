# BlinQ v7.1.8 — partial-year history recovery

The previous recovery guard only reopened dates when an entire `history-YYYY.parquet` file was missing.

A history run executed on the older v7.1.6 commit after manifest recovery can create a *partial* 2026 partition from only the newest pending days while `download_progress.json` still marks most of 2026 complete. Once that tiny partition exists, a missing-partition-only guard is no longer enough.

v7.1.8 adds a conservative partial-year detector for history mode:

- requested years with no parquet are reopened as before;
- requested years with at least 14 completed progress days are checked against dates physically represented in the parquet rows;
- only when fewer than 50% of completed days are represented is the year treated as catastrophically partial;
- only completed dates absent from physical history are reopened; represented dates and healthy years stay untouched.

This is a recovery safety net, not a normal recurring re-download policy.
