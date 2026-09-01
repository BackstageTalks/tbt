-- TBT v200 database schema.
-- Run once in Supabase SQL Editor before bootstrapping history.

create table if not exists public.matches (
    match_id text primary key,
    tour text not null check (tour in ('atp', 'wta')),
    scheduled_at timestamptz not null,
    player1_id text not null,
    player1_name text not null,
    player2_id text not null,
    player2_name text not null,
    surface text not null default 'unknown',
    tournament text not null default '',
    tournament_id text not null default '',
    tournament_level text not null default '',
    round_name text not null default '',
    player1_rank integer,
    player2_rank integer,
    winner_id text,
    status text not null default '',
    best_of integer,
    indoor boolean,
    stats jsonb not null default '{}'::jsonb,
    provider_payload jsonb not null default '{}'::jsonb,
    updated_at timestamptz not null default now()
);

create index if not exists matches_scheduled_at_idx on public.matches (scheduled_at);
create index if not exists matches_winner_date_idx on public.matches (winner_id, scheduled_at);
create index if not exists matches_players_idx on public.matches (player1_id, player2_id);

create table if not exists public.predictions (
    match_id text not null,
    model_version text not null,
    generated_at timestamptz not null,
    scheduled_at timestamptz not null,
    tour text not null,
    tournament text not null default '',
    surface text not null default 'unknown',
    round_name text not null default '',
    player1_id text not null,
    player1_name text not null,
    player1_rank integer,
    player2_id text not null,
    player2_name text not null,
    player2_rank integer,
    player1_probability double precision not null check (player1_probability between 0 and 1),
    player2_probability double precision not null check (player2_probability between 0 and 1),
    predicted_winner_id text not null,
    predicted_winner_name text not null,
    confidence_pct double precision not null,
    confidence_band text not null,
    features jsonb not null default '{}'::jsonb,
    signals jsonb not null default '[]'::jsonb,
    result_winner_id text,
    is_correct boolean,
    primary key (match_id, model_version)
);

create index if not exists predictions_scheduled_idx on public.predictions (scheduled_at);
create index if not exists predictions_generated_idx on public.predictions (generated_at desc);

create table if not exists public.model_versions (
    model_version text primary key,
    created_at timestamptz not null default now(),
    history_start timestamptz,
    history_end timestamptz,
    training_matches integer,
    holdout_metrics jsonb not null default '{}'::jsonb,
    metadata jsonb not null default '{}'::jsonb
);

create table if not exists public.backtest_runs (
    id bigint generated always as identity primary key,
    created_at timestamptz not null default now(),
    model_version text,
    report jsonb not null
);

-- Only the newest prediction per match is exposed through the public view.
create or replace view public.current_predictions
with (security_invoker = true)
as
select distinct on (match_id) *
from public.predictions
order by match_id, generated_at desc;

alter table public.matches enable row level security;
alter table public.predictions enable row level security;
alter table public.model_versions enable row level security;
alter table public.backtest_runs enable row level security;

-- Browser clients may read predictions and evaluation metadata only.
-- Server-side history ingestion/training uses SUPABASE_SERVICE_ROLE_KEY and bypasses RLS.
do $$ begin
    if not exists (
        select 1 from pg_policies where schemaname='public' and tablename='predictions' and policyname='public_read_predictions'
    ) then
        create policy public_read_predictions on public.predictions for select to anon using (true);
    end if;
    if not exists (
        select 1 from pg_policies where schemaname='public' and tablename='model_versions' and policyname='public_read_model_versions'
    ) then
        create policy public_read_model_versions on public.model_versions for select to anon using (true);
    end if;
    if not exists (
        select 1 from pg_policies where schemaname='public' and tablename='backtest_runs' and policyname='public_read_backtests'
    ) then
        create policy public_read_backtests on public.backtest_runs for select to anon using (true);
    end if;
end $$;

grant select on public.predictions, public.current_predictions, public.model_versions, public.backtest_runs to anon;
