create table public.securebase_users (
    id uuid primary key default gen_random_uuid(),
    email text not null,
    full_name text not null,
    password_hash text,
    role public.securebase_role not null default 'member',
    email_verified_at timestamptz,
    verification_token_hash text,
    verification_expires_at timestamptz,
    invitation_token_hash text,
    invitation_expires_at timestamptz,
    auth_version integer not null default 0,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint securebase_users_email_length check (length(email) <= 254),
    constraint securebase_users_name_length check (length(full_name) between 2 and 120),
    constraint securebase_users_auth_state check (
        (password_hash is not null and invitation_token_hash is null)
        or (password_hash is null and invitation_token_hash is not null)
    )
);

create unique index securebase_users_email_lower_idx
    on public.securebase_users (lower(email));

create unique index securebase_users_verification_token_idx
    on public.securebase_users (verification_token_hash)
    where verification_token_hash is not null;

create unique index securebase_users_invitation_token_idx
    on public.securebase_users (invitation_token_hash)
    where invitation_token_hash is not null;

alter table public.securebase_users enable row level security;
revoke all on table public.securebase_users from anon, authenticated;
grant select, insert, update, delete on table public.securebase_users to service_role;
