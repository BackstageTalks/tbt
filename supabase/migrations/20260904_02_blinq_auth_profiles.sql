-- BlinQ V19: Supabase Auth-backed account profiles and plan entitlements.
-- Safe to run once after the earlier app_settings migration.

create table if not exists public.user_profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text not null,
  display_name text not null default 'BlinQ User',
  plan text not null default 'free' check (plan in ('free','pro','elite','legend','goat','admin')),
  plan_label text not null default 'Free',
  entitlement_expires_at timestamptz,
  avatar_variant text not null default 'a' check (avatar_variant in ('a','b')),
  avatar_url text not null default '',
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists user_profiles_plan_idx on public.user_profiles(plan);
create index if not exists user_profiles_email_idx on public.user_profiles(lower(email));

alter table public.user_profiles enable row level security;

-- Signed-in users can read only their own profile. Plan changes are intentionally
-- not writable from the browser; they go through the x-admin-key protected API.
drop policy if exists "user_profiles_select_own" on public.user_profiles;
create policy "user_profiles_select_own"
on public.user_profiles
for select
to authenticated
using (auth.uid() = id);

revoke insert, update, delete on public.user_profiles from anon, authenticated;
grant select on public.user_profiles to authenticated;

create or replace function public.blinq_touch_user_profile_updated_at()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists blinq_user_profiles_touch_updated_at on public.user_profiles;
create trigger blinq_user_profiles_touch_updated_at
before update on public.user_profiles
for each row execute function public.blinq_touch_user_profile_updated_at();

create or replace function public.blinq_handle_new_auth_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.user_profiles (
    id,
    email,
    display_name,
    plan,
    plan_label,
    avatar_variant,
    is_active
  ) values (
    new.id,
    coalesce(new.email, ''),
    coalesce(nullif(new.raw_user_meta_data ->> 'display_name', ''), nullif(split_part(coalesce(new.email, ''), '@', 1), ''), 'BlinQ User'),
    'free',
    'Free',
    'a',
    true
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists blinq_on_auth_user_created on auth.users;
create trigger blinq_on_auth_user_created
after insert on auth.users
for each row execute function public.blinq_handle_new_auth_user();

-- Backfill users that existed before this migration.
insert into public.user_profiles (
  id,
  email,
  display_name,
  plan,
  plan_label,
  avatar_variant,
  is_active
)
select
  u.id,
  coalesce(u.email, ''),
  coalesce(nullif(u.raw_user_meta_data ->> 'display_name', ''), nullif(split_part(coalesce(u.email, ''), '@', 1), ''), 'BlinQ User'),
  'free',
  'Free',
  'a',
  true
from auth.users u
on conflict (id) do nothing;
