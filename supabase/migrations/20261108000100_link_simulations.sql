-- Laboratório de rede: histórico das simulações do caminho de um alerta.
-- Acesso somente pelo backend (service_role).

create table public.securebase_link_simulations (
    id uuid primary key,
    home_id uuid not null references public.securebase_homes(id) on delete cascade,
    created_by uuid references public.securebase_users(id) on delete set null,
    created_at timestamptz not null default now(),
    scenario text not null,
    intensity double precision not null,
    defenses jsonb not null,
    trials integer not null,
    seed bigint not null,
    model_version text not null,
    verdict text not null,
    delivery_rate double precision not null,
    result jsonb not null,
    constraint securebase_link_simulations_scenario
        check (scenario in ('baseline', 'jamming', 'wan_failure', 'fake_base_station')),
    constraint securebase_link_simulations_verdict
        check (verdict in ('delivered', 'aware', 'degraded', 'local_only', 'silent')),
    constraint securebase_link_simulations_defenses check (jsonb_typeof(defenses) = 'array'),
    constraint securebase_link_simulations_result check (jsonb_typeof(result) = 'object'),
    constraint securebase_link_simulations_parameters check (
        intensity between 0 and 1
        and trials between 50 and 2000
        and seed >= 0
        and delivery_rate between 0 and 1
    )
);

create index securebase_link_simulations_home_idx
    on public.securebase_link_simulations (home_id, created_at desc);

alter table public.securebase_link_simulations enable row level security;
revoke all on table public.securebase_link_simulations from anon, authenticated;
grant select, insert on table public.securebase_link_simulations to service_role;
