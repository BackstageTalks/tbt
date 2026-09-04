-- BlinQ V19.2: Telegram identity metadata + public avatar asset bucket.
-- Run after 20260904_02_blinq_auth_profiles.sql.

alter table public.user_profiles
  add column if not exists auth_provider text not null default 'email',
  add column if not exists telegram_id text not null default '',
  add column if not exists telegram_handle text not null default '',
  add column if not exists telegram_photo_url text not null default '';

create index if not exists user_profiles_telegram_id_idx
  on public.user_profiles(telegram_id)
  where telegram_id <> '';

-- Public assets are readable by the website. Writes are performed only by the
-- Azure Function using SUPABASE_SERVICE_ROLE_KEY.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'blinq-assets',
  'blinq-assets',
  true,
  1500000,
  array['image/png','image/jpeg','image/webp']::text[]
)
on conflict (id) do update set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

-- Refresh the new-user profile trigger so Telegram/OIDC users get a sensible
-- display name even when their provider does not return an email address.
create or replace function public.blinq_handle_new_auth_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  provider_name text;
  preferred_username text;
  telegram_user_id text;
  telegram_picture text;
begin
  provider_name := coalesce(new.raw_app_meta_data ->> 'provider', 'email');
  preferred_username := coalesce(new.raw_user_meta_data ->> 'preferred_username', new.raw_user_meta_data ->> 'username', '');
  telegram_user_id := case when provider_name like 'custom:telegram%' then coalesce(new.raw_user_meta_data ->> 'id', new.raw_user_meta_data ->> 'sub', '') else '' end;
  telegram_picture := case when provider_name like 'custom:telegram%' then coalesce(new.raw_user_meta_data ->> 'picture', new.raw_user_meta_data ->> 'photo_url', '') else '' end;

  insert into public.user_profiles (
    id, email, display_name, plan, plan_label, avatar_variant, avatar_url,
    auth_provider, telegram_id, telegram_handle, telegram_photo_url, is_active
  ) values (
    new.id,
    coalesce(new.email, ''),
    coalesce(
      nullif(new.raw_user_meta_data ->> 'display_name', ''),
      nullif(new.raw_user_meta_data ->> 'name', ''),
      nullif(preferred_username, ''),
      nullif(split_part(coalesce(new.email, ''), '@', 1), ''),
      'BlinQ User'
    ),
    'free', 'Free', 'a', '', provider_name, telegram_user_id,
    case when provider_name like 'custom:telegram%' then preferred_username else '' end,
    telegram_picture, true
  )
  on conflict (id) do nothing;
  return new;
end;
$$;
