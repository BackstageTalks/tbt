-- BlinQ persistent UI/admin configuration
create table if not exists public.app_settings (
  setting_key text primary key,
  value jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

alter table public.app_settings enable row level security;

grant select on table public.app_settings to anon, authenticated;

drop policy if exists app_settings_public_read on public.app_settings;
create policy app_settings_public_read
  on public.app_settings
  for select
  to anon, authenticated
  using (true);

-- No anonymous write policy is created. Azure Functions writes with the
-- SUPABASE_SERVICE_ROLE_KEY and therefore bypasses RLS.
