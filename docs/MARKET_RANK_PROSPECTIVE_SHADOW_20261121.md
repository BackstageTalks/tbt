# Prospective Market Rank Shadow — execution contract (2026-11-21)

**Owner-authorized: prospective private shadow ONLY.** Not permission to promote a champion, alter public TOP/PRIME/VALUE, modify CDB, change bookmaker price floors or train.

## Reuse the existing pipeline
- The already merged code in #1733 (market ranking) and #1735 (optional TOP-side veto) stays unchanged for public selection.
- The existing guarded data.yml refresh/current-refresh sets TBT_MARKET_RANK_SHADOW_ENABLED=true only for previously authorized provider jobs, unless vars.TBT_MARKET_RANK_SHADOW_DISABLED=true. No new cron or paid API job.
- scripts/pipeline.py:_publish_predictions saves research-only receipts in the already-native monthly private tbt-predictions-v1/selection_candidates_YYYY-MM.json.gz release asset. It does not invent a new canonical writer or publication path.
- A separately instantiated ReleaseStore downloads the committed monthly gzip and verifies the exact SHA256 of bytes and the first-day receipt. PRIVATE_READBACK_VERIFIED is logged only after that independent check, never from an upload's success message.
- Subsequent refreshes can score canonical settled results from the immutable prestart receipts, without backfilling outcomes into the original source capture.

## Three directly comparable parallel variants
| Variant | Ordering | TOP market-side veto | Emergency TOP |
|---|---|---|---|
| champion | unchanged model | OFF | OFF |
| market_anchored | 80% market/20% model, logit | OFF | OFF |
| market_anchored_top_veto | identical market rank | ON (prestart fair below 0.5) | OFF |

All variants use the *same* selector, frozen same-slate provider-discovered inputs, category thresholds and original model. Each shadow-only receipt has exact match/event/player identity, observation and scheduled timestamps, model version, fair/price evidence, policy name and SHA256-backed unique receipt. Temporary environment overrides are restored before any public processing. Not one of these variants is a public offer.

Only timezone-aware, pre-start matches at least 10 minutes away enter the first recorded slate; model created_at must be before actual observation. Market fair needs complete same-book two-sided probabilities and credible provider identity. Because adapters may backdate original source captured_at to a projected selection time, actual post-enrichment observation time is used as conservative point-in-time proof. Unverifiable fair falls back to model ranking, never post-start bookmaker information. PropLine needs confirmed bookmaker and provider event identity.

The first eligible captured slate per BlinQ betting day is immutable and SHA256-sealed. Later runs must not alter already issued counterfactual tips. No source-day completeness guarantee beyond the provider-discovered fixtures; missed days and unobserved matches remain explicit limitations.

## Analysis, status and rollback
Read-only comparison uses the exact canonical match ID, both player IDs, scheduled start, actual completed match winner and observed settlement after the start. Report issued/settled/correct, hit rate and optional ROI separately for TOP, PRIME and VALUE across all variants; do not train or promote on these diagnostics.

Passing tests/CI does not mean a real private release was written. A real authorized provider refresh, fresh remote byte read-back, a confirmed first-day receipt and settled outcomes are the LIVE proof. At least 400 valid prospective paired observations, honest daily N comparisons, ATP/WTA breakdown and market baseline are needed before any superiority decision. Unlike a champion promotion, new shadow enrollment does not require a retrained model backup.

Stop new shadow receipts using vars.TBT_MARKET_RANK_SHADOW_DISABLED=true, preserving prior frozen evidence. Public ranking and emergency/veto settings remain independently gated and default-OFF. No extra API calls or CDB writes are authorized by this research.

Security issue #229 in BackstageTalks/tbt-data remains separate. Do not expose credential values or claim token revocation/backup rotation without verified administrative proof.
