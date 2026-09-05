-- DESTRUCTIVE MAINTENANCE: execute only after:
-- 1) history_manifest.json + history-2021..2026.parquet are verified in private GH,
-- 2) a V3 champion model with embedded FeatureBuilder state is published,
-- 3) one production prediction refresh succeeds with that champion.
--
-- Supabase hot tier policy: keep 2025-01-01 and newer only.

-- Read-only preview first:
select
    extract(year from scheduled_at)::int as year,
    count(*) as rows_to_review
from public.matches
group by 1
order by 1;

-- Uncomment only after the checklist above is green.
-- begin;
-- delete from public.matches
--  where scheduled_at < timestamptz '2025-01-01 00:00:00+00';
-- commit;
--
-- VACUUM (FULL, ANALYZE) public.matches;
-- REINDEX TABLE public.matches;
--
-- Verify physical size afterwards:
-- select
--     pg_size_pretty(pg_total_relation_size('public.matches')) as total_size,
--     pg_size_pretty(pg_relation_size('public.matches')) as heap,
--     pg_size_pretty(pg_indexes_size('public.matches')) as indexes;
