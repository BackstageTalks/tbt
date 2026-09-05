-- V20.5 Final Data Architecture
-- Lean hot-tier storage for public.matches + separate environment payload.
-- Run AFTER the GitHub year partitions are verified and Supabase is writable.

begin;

create table if not exists public.match_environment (
    match_id text primary key references public.matches(match_id) on delete cascade,
    scheduled_at timestamptz not null,
    environment jsonb not null default '{}'::jsonb,
    updated_at timestamptz not null default now()
);

create index if not exists idx_match_environment_scheduled_at
    on public.match_environment(scheduled_at);

alter table public.match_environment enable row level security;
-- Intentionally no anon/authenticated policy. The service-role server path owns it.

create or replace function public.tbt_touch_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at := now();
    return new;
end;
$$;

drop trigger if exists trg_matches_touch_updated_at on public.matches;
create trigger trg_matches_touch_updated_at
before update on public.matches
for each row execute function public.tbt_touch_updated_at();

create or replace function public.tbt_touch_match_from_environment()
returns trigger
language plpgsql
as $$
begin
    update public.matches
       set updated_at = now()
     where match_id = new.match_id;
    return new;
end;
$$;

drop trigger if exists trg_match_environment_touch_match on public.match_environment;
create trigger trg_match_environment_touch_match
after insert or update on public.match_environment
for each row execute function public.tbt_touch_match_from_environment();

-- Preserve already-enriched 2025+ environment before compacting provider_payload.
insert into public.match_environment(match_id, scheduled_at, environment, updated_at)
select
    m.match_id,
    m.scheduled_at,
    m.provider_payload -> '_tbt_environment',
    now()
from public.matches m
where m.scheduled_at >= timestamptz '2025-01-01 00:00:00+00'
  and jsonb_typeof(m.provider_payload -> '_tbt_environment') = 'object'
  and m.provider_payload -> '_tbt_environment' <> '{}'::jsonb
on conflict (match_id) do update
set scheduled_at = excluded.scheduled_at,
    environment = excluded.environment,
    updated_at = now();

-- Compact the existing hot provider payload. Unknown/raw response keys are dropped.
-- Canonical match fields remain first-class columns in public.matches.
update public.matches m
set provider_payload = jsonb_strip_nulls(
    jsonb_build_object(
        '_tbt_provider_event_id', coalesce(
            m.provider_payload -> '_tbt_provider_event_id',
            m.provider_payload -> 'provider_event_id',
            m.provider_payload -> 'event_id',
            m.provider_payload -> 'eventId',
            m.provider_payload -> 'id',
            m.provider_payload #> '{event,id}'
        ),
        '_tbt_source_category_id', m.provider_payload -> '_tbt_source_category_id',
        '_tbt_source_category_name', m.provider_payload -> '_tbt_source_category_name',
        'tournament', jsonb_strip_nulls(
            jsonb_build_object(
                'id', m.provider_payload #> '{tournament,id}',
                'name', m.provider_payload #> '{tournament,name}',
                'city', m.provider_payload #> '{tournament,city}',
                'country', m.provider_payload #> '{tournament,country}',
                'uniqueTournament', jsonb_strip_nulls(
                    jsonb_build_object(
                        'id', m.provider_payload #> '{tournament,uniqueTournament,id}',
                        'name', m.provider_payload #> '{tournament,uniqueTournament,name}',
                        'city', m.provider_payload #> '{tournament,uniqueTournament,city}',
                        'country', m.provider_payload #> '{tournament,uniqueTournament,country}'
                    )
                )
            )
        ),
        'venue', jsonb_strip_nulls(
            jsonb_build_object(
                'id', m.provider_payload #> '{venue,id}',
                'name', m.provider_payload #> '{venue,name}',
                'city', m.provider_payload #> '{venue,city}',
                'country', m.provider_payload #> '{venue,country}',
                'countryName', m.provider_payload #> '{venue,countryName}'
            )
        ),
        'city', m.provider_payload -> 'city',
        'venueCity', m.provider_payload -> 'venueCity',
        'countryName', m.provider_payload -> 'countryName',
        'country', m.provider_payload -> 'country'
    )
)
where m.scheduled_at >= timestamptz '2025-01-01 00:00:00+00';

commit;

-- Reclaim TOAST space created by the old raw JSON. VACUUM FULL takes an exclusive
-- lock on matches; run it in a maintenance window after the transaction above.
-- VACUUM (FULL, ANALYZE) public.matches;
-- REINDEX TABLE public.matches;
