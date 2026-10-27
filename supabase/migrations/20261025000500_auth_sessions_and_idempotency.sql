create table public.securebase_refresh_sessions (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references public.securebase_users(id) on delete cascade,
    family_id uuid not null,
    token_hash text not null unique,
    auth_version integer not null,
    expires_at timestamptz not null,
    revoked_at timestamptz,
    replaced_by_hash text,
    created_at timestamptz not null default now(),
    constraint securebase_refresh_token_hash_length check (length(token_hash) = 64)
);

create index securebase_refresh_sessions_user_idx
    on public.securebase_refresh_sessions (user_id);
create index securebase_refresh_sessions_family_idx
    on public.securebase_refresh_sessions (family_id);
create index securebase_refresh_sessions_expiry_idx
    on public.securebase_refresh_sessions (expires_at);

alter table public.securebase_refresh_sessions enable row level security;
revoke all on table public.securebase_refresh_sessions from anon, authenticated;
grant select, insert, update, delete on table public.securebase_refresh_sessions to service_role;

create table public.securebase_idempotency_keys (
    scope text not null,
    key_hash text not null,
    request_hash text not null,
    status_code smallint,
    response_body jsonb,
    created_at timestamptz not null default now(),
    expires_at timestamptz not null default now() + interval '24 hours',
    primary key (scope, key_hash),
    constraint securebase_idempotency_hash_length check (
        length(key_hash) = 64 and length(request_hash) = 64
    ),
    constraint securebase_idempotency_result_pair check (
        (status_code is null and response_body is null)
        or (status_code between 200 and 299 and response_body is not null)
    )
);

create index securebase_idempotency_expiry_idx
    on public.securebase_idempotency_keys (expires_at);

alter table public.securebase_idempotency_keys enable row level security;
revoke all on table public.securebase_idempotency_keys from anon, authenticated;
grant select, insert, update, delete on table public.securebase_idempotency_keys to service_role;

create function public.securebase_create_refresh_session(
    p_user_id uuid,
    p_family_id uuid,
    p_token_hash text,
    p_auth_version integer,
    p_expires_at timestamptz
) returns void
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
    with expired_rows as (
        select ctid
          from public.securebase_refresh_sessions
         where expires_at <= now()
         order by expires_at
         limit 500
         for update skip locked
    )
    delete from public.securebase_refresh_sessions
     where ctid in (select ctid from expired_rows);

    insert into public.securebase_refresh_sessions (
        user_id, family_id, token_hash, auth_version, expires_at
    )
    values (p_user_id, p_family_id, p_token_hash, p_auth_version, p_expires_at);
end;
$$;

create function public.securebase_rotate_refresh_session(
    p_token_hash text,
    p_new_token_hash text
) returns table(state text, user_id uuid, family_id uuid, auth_version integer)
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    current_session public.securebase_refresh_sessions%rowtype;
    current_auth_version integer;
begin
    with expired_rows as (
        select ctid
          from public.securebase_refresh_sessions
         where expires_at <= now()
         order by expires_at
         limit 500
         for update skip locked
    )
    delete from public.securebase_refresh_sessions
     where ctid in (select ctid from expired_rows);

    select *
      into current_session
      from public.securebase_refresh_sessions
     where token_hash = p_token_hash
     for update;

    if not found then
        return query select 'invalid'::text, null::uuid, null::uuid, null::integer;
        return;
    end if;

    if current_session.revoked_at is not null then
        update public.securebase_refresh_sessions
           set revoked_at = coalesce(revoked_at, now())
         where family_id = current_session.family_id;
        return query select 'reused'::text, null::uuid, null::uuid, null::integer;
        return;
    end if;

    select account_row.auth_version
      into current_auth_version
      from public.securebase_users as account_row
     where account_row.id = current_session.user_id;

    if current_auth_version is null
       or current_auth_version <> current_session.auth_version then
        update public.securebase_refresh_sessions
           set revoked_at = coalesce(revoked_at, now())
         where family_id = current_session.family_id;
        return query select 'stale'::text, null::uuid, null::uuid, null::integer;
        return;
    end if;

    if current_session.expires_at <= now() then
        update public.securebase_refresh_sessions
           set revoked_at = now()
         where id = current_session.id;
        return query select 'expired'::text, null::uuid, null::uuid, null::integer;
        return;
    end if;

    update public.securebase_refresh_sessions
       set revoked_at = now(), replaced_by_hash = p_new_token_hash
     where id = current_session.id;

    insert into public.securebase_refresh_sessions (
        user_id, family_id, token_hash, auth_version, expires_at
    )
    values (
        current_session.user_id,
        current_session.family_id,
        p_new_token_hash,
        current_session.auth_version,
        current_session.expires_at
    );

    return query select
        'rotated'::text,
        current_session.user_id,
        current_session.family_id,
        current_session.auth_version;
end;
$$;

create function public.securebase_revoke_refresh_session(p_token_hash text)
returns void
language sql
security definer
set search_path = public, pg_temp
as $$
    update public.securebase_refresh_sessions
       set revoked_at = coalesce(revoked_at, now())
     where family_id = (
         select family_id
           from public.securebase_refresh_sessions
          where token_hash = p_token_hash
     );
$$;

create function public.securebase_revoke_user_refresh_sessions(p_user_id uuid)
returns void
language sql
security definer
set search_path = public, pg_temp
as $$
    update public.securebase_refresh_sessions
       set revoked_at = coalesce(revoked_at, now())
     where user_id = p_user_id;
$$;

create function public.securebase_claim_idempotency_key(
    p_scope text,
    p_key_hash text,
    p_request_hash text
) returns table(state text, status_code smallint, response_body jsonb)
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    existing public.securebase_idempotency_keys%rowtype;
begin
    perform pg_advisory_xact_lock(hashtextextended(p_scope || ':' || p_key_hash, 0));

    with expired_rows as (
        select ctid
          from public.securebase_idempotency_keys
         where expires_at <= now()
         order by expires_at
         limit 500
         for update skip locked
    )
    delete from public.securebase_idempotency_keys
     where ctid in (select ctid from expired_rows);

    delete from public.securebase_idempotency_keys
     where scope = p_scope and key_hash = p_key_hash and expires_at <= now();

    select *
      into existing
      from public.securebase_idempotency_keys
     where scope = p_scope and key_hash = p_key_hash;

    if not found then
        insert into public.securebase_idempotency_keys (scope, key_hash, request_hash)
        values (p_scope, p_key_hash, p_request_hash);
        return query select 'new'::text, null::smallint, null::jsonb;
        return;
    end if;

    if existing.request_hash <> p_request_hash then
        return query select 'conflict'::text, null::smallint, null::jsonb;
        return;
    end if;

    if existing.response_body is not null then
        return query select 'replay'::text, existing.status_code, existing.response_body;
        return;
    end if;

    return query select 'in_progress'::text, null::smallint, null::jsonb;
end;
$$;

create function public.securebase_complete_idempotency_key(
    p_scope text,
    p_key_hash text,
    p_request_hash text,
    p_status_code smallint,
    p_response_body jsonb
) returns void
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
    update public.securebase_idempotency_keys
       set status_code = p_status_code,
           response_body = p_response_body
     where scope = p_scope
       and key_hash = p_key_hash
       and request_hash = p_request_hash
       and response_body is null
       and expires_at > now();

    if not found then
        raise exception 'idempotency claim could not be completed';
    end if;
end;
$$;

create function public.securebase_release_idempotency_key(
    p_scope text,
    p_key_hash text,
    p_request_hash text
) returns void
language sql
security definer
set search_path = public, pg_temp
as $$
    delete from public.securebase_idempotency_keys
     where scope = p_scope
       and key_hash = p_key_hash
       and request_hash = p_request_hash
       and response_body is null;
$$;

revoke all on function public.securebase_create_refresh_session(uuid, uuid, text, integer, timestamptz)
    from public, anon, authenticated;
revoke all on function public.securebase_rotate_refresh_session(text, text)
    from public, anon, authenticated;
revoke all on function public.securebase_revoke_refresh_session(text)
    from public, anon, authenticated;
revoke all on function public.securebase_revoke_user_refresh_sessions(uuid)
    from public, anon, authenticated;
revoke all on function public.securebase_claim_idempotency_key(text, text, text)
    from public, anon, authenticated;
revoke all on function public.securebase_complete_idempotency_key(text, text, text, smallint, jsonb)
    from public, anon, authenticated;
revoke all on function public.securebase_release_idempotency_key(text, text, text)
    from public, anon, authenticated;

grant execute on function public.securebase_create_refresh_session(uuid, uuid, text, integer, timestamptz)
    to service_role;
grant execute on function public.securebase_rotate_refresh_session(text, text)
    to service_role;
grant execute on function public.securebase_revoke_refresh_session(text)
    to service_role;
grant execute on function public.securebase_revoke_user_refresh_sessions(uuid)
    to service_role;
grant execute on function public.securebase_claim_idempotency_key(text, text, text)
    to service_role;
grant execute on function public.securebase_complete_idempotency_key(text, text, text, smallint, jsonb)
    to service_role;
grant execute on function public.securebase_release_idempotency_key(text, text, text)
    to service_role;
