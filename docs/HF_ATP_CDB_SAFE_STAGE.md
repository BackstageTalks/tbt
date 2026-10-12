# BlinQ — Hugging Face ATP 2015–2025 safe staging

Status: READ-ONLY SOURCE QUARANTINE — **not a CDB import authorization**.

Usage:

```sh
python normalize_hf_atp.py --source HugF.zip --output staging
python -m unittest -v test_normalize_hf_atp.py
```

The output `staging/quarantined-observations.jsonl` contains normalized, source-linked post-match candidate observations, explicitly `import_ready=false`. `staging/report.json` carries measured counts and SHA-256 of source bytes. No canonical CDB writes, provider API requests, model training, or GitHub Actions jobs.

Excluded: entire `ytd_*` family, winner-first predictive labels, player season ratings, service/return-games-played (2025 zeros), invalid fractional rates, conflicting duplicate source URLs and rows without two-sided match stats. Archived raw files are not changed or deleted.

Unmet gates before production: underlying ATP Tour data rights, independent ATP Tour stats URL to canonical match/player IDs (not fuzzy names), currently deployed CDB NULL and conflicts comparison, immutable prewrite backup, global single-writer lock, year partition CAS and independent full remote read-back.

Source: https://huggingface.co/datasets/Yahya777777/ATP-Tennis-Matches-Dataset-2015-to-2025