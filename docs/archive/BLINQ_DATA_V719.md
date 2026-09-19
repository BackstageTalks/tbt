# BlinQ v7.1.9 — data / environment optimisation

- Environment resolver v4:
  - strips ITF tour/gender/draw suffixes from tournament labels;
  - extracts explicit ITF provider country tokens (e.g. `M-ITF-SRB` -> `RS`);
  - adds high-confidence aliases for recurring unresolved hubs such as Kutaisi, Maringa, Hurghada, Monastir, Antalya, Sharm El Sheikh, Heraklion and Oeiras;
  - keeps fail-closed exact geocoding and never guesses a country from a player name.
- Mega-data is now defensive-first:
  - provider probe;
  - history gap recovery before enrichment;
  - baseline statistics inventory;
  - statistics -> SG -> ACE;
  - statistics tail consumes all unused Tennis API headroom;
  - post-run history audit and before/after statistics artifacts.
- Normal history/statistics workflows now upload their real download report instead of emitting the irrelevant history-repair artifact message.
