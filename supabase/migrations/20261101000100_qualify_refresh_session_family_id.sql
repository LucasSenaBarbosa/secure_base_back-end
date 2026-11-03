create or replace function public.securebase_rotate_refresh_session(
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
        update public.securebase_refresh_sessions as refresh_session
           set revoked_at = coalesce(refresh_session.revoked_at, now())
         where refresh_session.family_id = current_session.family_id;
        return query select 'reused'::text, null::uuid, null::uuid, null::integer;
        return;
    end if;

    select account_row.auth_version
      into current_auth_version
      from public.securebase_users as account_row
     where account_row.id = current_session.user_id;

    if current_auth_version is null
       or current_auth_version <> current_session.auth_version then
        update public.securebase_refresh_sessions as refresh_session
           set revoked_at = coalesce(refresh_session.revoked_at, now())
         where refresh_session.family_id = current_session.family_id;
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
