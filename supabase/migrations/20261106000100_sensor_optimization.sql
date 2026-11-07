-- Laboratório de otimização de sensores (NSGA-II).
-- Layout da residência, execuções, soluções da fronteira de Pareto e
-- configurações manuais. Acesso somente pelo backend (service_role).

create table public.securebase_home_layouts (
    home_id uuid primary key references public.securebase_homes(id) on delete cascade,
    layout jsonb not null,
    version integer not null default 1,
    updated_by uuid references public.securebase_users(id) on delete set null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint securebase_home_layouts_object check (jsonb_typeof(layout) = 'object'),
    constraint securebase_home_layouts_version check (version > 0)
);

create table public.securebase_optimization_runs (
    id uuid primary key,
    home_id uuid not null references public.securebase_homes(id) on delete cascade,
    created_by uuid references public.securebase_users(id) on delete set null,
    created_at timestamptz not null default now(),
    layout_version integer not null,
    layout_snapshot jsonb not null,
    library text not null,
    population_size integer not null,
    generations integer not null,
    seed bigint not null,
    evaluations integer not null,
    duration_ms integer not null,
    status text not null,
    solution_count integer not null,
    constraint securebase_optimization_runs_status
        check (status in ('completed', 'no_feasible_solution')),
    constraint securebase_optimization_runs_snapshot
        check (jsonb_typeof(layout_snapshot) = 'object'),
    constraint securebase_optimization_runs_parameters check (
        population_size between 10 and 200
        and generations between 1 and 300
        and seed >= 0
        and evaluations >= 0
        and duration_ms >= 0
        and solution_count >= 0
    )
);

create index securebase_optimization_runs_home_idx
    on public.securebase_optimization_runs (home_id, created_at desc);

create table public.securebase_optimization_solutions (
    id uuid primary key,
    run_id uuid not null references public.securebase_optimization_runs(id) on delete cascade,
    solution_index integer not null,
    sensors jsonb not null,
    coverage double precision not null,
    cost double precision not null,
    vulnerability double precision not null,
    sensors_by_type jsonb not null,
    constraint securebase_optimization_solutions_unique unique (run_id, solution_index),
    constraint securebase_optimization_solutions_sensors check (jsonb_typeof(sensors) = 'array'),
    constraint securebase_optimization_solutions_metrics check (
        coverage between 0 and 1 and vulnerability between 0 and 1 and cost >= 0
    )
);

create table public.securebase_manual_configurations (
    id uuid primary key default gen_random_uuid(),
    home_id uuid not null references public.securebase_homes(id) on delete cascade,
    name text not null,
    sensors jsonb not null,
    created_by uuid references public.securebase_users(id) on delete set null,
    created_at timestamptz not null default now(),
    constraint securebase_manual_configurations_name check (length(trim(name)) between 1 and 120),
    constraint securebase_manual_configurations_sensors check (jsonb_typeof(sensors) = 'array')
);

create index securebase_manual_configurations_home_idx
    on public.securebase_manual_configurations (home_id, created_at desc);

alter table public.securebase_home_layouts enable row level security;
alter table public.securebase_optimization_runs enable row level security;
alter table public.securebase_optimization_solutions enable row level security;
alter table public.securebase_manual_configurations enable row level security;
revoke all on table public.securebase_home_layouts, public.securebase_optimization_runs,
    public.securebase_optimization_solutions, public.securebase_manual_configurations
    from anon, authenticated;
grant select, insert, update, delete on table public.securebase_home_layouts,
    public.securebase_optimization_runs, public.securebase_optimization_solutions,
    public.securebase_manual_configurations to service_role;

-- Grava a execução e suas soluções na mesma transação.
create function public.securebase_create_optimization_run(p_run jsonb, p_solutions jsonb)
returns void
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
    if jsonb_typeof(p_solutions) <> 'array' then
        raise exception 'p_solutions must be an array';
    end if;

    insert into public.securebase_optimization_runs (
        id, home_id, created_by, layout_version, layout_snapshot, library,
        population_size, generations, seed, evaluations, duration_ms, status, solution_count
    )
    values (
        (p_run->>'id')::uuid,
        (p_run->>'home_id')::uuid,
        nullif(p_run->>'created_by', '')::uuid,
        (p_run->>'layout_version')::integer,
        p_run->'layout_snapshot',
        p_run->>'library',
        (p_run->>'population_size')::integer,
        (p_run->>'generations')::integer,
        (p_run->>'seed')::bigint,
        (p_run->>'evaluations')::integer,
        (p_run->>'duration_ms')::integer,
        p_run->>'status',
        jsonb_array_length(p_solutions)
    );

    insert into public.securebase_optimization_solutions (
        id, run_id, solution_index, sensors, coverage, cost, vulnerability, sensors_by_type
    )
    select
        (item->>'id')::uuid,
        (p_run->>'id')::uuid,
        (item->>'solution_index')::integer,
        item->'sensors',
        (item->>'coverage')::double precision,
        (item->>'cost')::double precision,
        (item->>'vulnerability')::double precision,
        item->'sensors_by_type'
    from jsonb_array_elements(p_solutions) as item;
end;
$$;

revoke all on function public.securebase_create_optimization_run(jsonb, jsonb)
    from public, anon, authenticated;
grant execute on function public.securebase_create_optimization_run(jsonb, jsonb)
    to service_role;
