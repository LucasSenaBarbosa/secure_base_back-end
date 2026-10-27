create type public.securebase_role as enum ('primary', 'member');

create table public.user_profiles (
    id uuid primary key references auth.users (id) on delete cascade,
    email text not null,
    full_name text not null,
    role public.securebase_role not null default 'member',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index user_profiles_email_lower_idx
    on public.user_profiles (lower(email));

alter table public.user_profiles enable row level security;
revoke all on table public.user_profiles from anon, authenticated;
grant select on table public.user_profiles to service_role;

create function public.sync_securebase_user_profile()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    insert into public.user_profiles (id, email, full_name)
    values (
        new.id,
        new.email,
        coalesce(nullif(trim(new.raw_user_meta_data ->> 'full_name'), ''), new.email)
    )
    on conflict (id) do update
    set email = excluded.email,
        full_name = excluded.full_name,
        updated_at = now();
    return new;
end;
$$;

create trigger on_auth_user_created_or_updated
    after insert or update of email, raw_user_meta_data on auth.users
    for each row execute function public.sync_securebase_user_profile();
