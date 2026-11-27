# Match Status ready for a 10-minute external clock (2026-11-27)
Owner moves cron-job.org Match Status 15 -> 10 min (more room for results + bracket).
Windows that assumed 15 min would fire more often: morning offer alarm now once per Bratislava day (checks runs since 06:00), calibration monitor once per UTC slot. Frozen 7.2.1 and CDB inbox were already deduped; CLV keeps minute 00. Works with 15 min too.
Revert: revert this PR.
