create table public.securebase_homes (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    primary_user_id uuid not null references public.securebase_users(id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint securebase_homes_name_length check (length(trim(name)) between 2 and 120)
);

create index securebase_homes_primary_user_idx
    on public.securebase_homes (primary_user_id);

create table public.securebase_home_members (
    home_id uuid not null references public.securebase_homes(id) on delete cascade,
    user_id uuid not null references public.securebase_users(id) on delete cascade,
    created_at timestamptz not null default now(),
    primary key (home_id, user_id)
);

create index securebase_home_members_user_idx
    on public.securebase_home_members (user_id);

insert into public.securebase_homes (name, primary_user_id)
select left(full_name || ' - casa', 120), id
from public.securebase_users
where role = 'primary';

update public.securebase_users
set role = 'member', updated_at = now()
where role = 'primary';

alter table public.securebase_homes enable row level security;
alter table public.securebase_home_members enable row level security;
revoke all on table public.securebase_homes, public.securebase_home_members
    from anon, authenticated;
grant select, insert, update, delete on table public.securebase_homes,
    public.securebase_home_members to service_role;
