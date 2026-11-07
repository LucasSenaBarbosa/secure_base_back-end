import asyncio
import secrets
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError

from modules.repository.supabase_repository import SupabaseRepository
from modules.schemas.auth_schemas import UserProfile
from modules.schemas.optimization_schemas import (
    CompareRequest,
    Comparison,
    ComparisonEntry,
    Evaluation,
    EvaluationRequest,
    HomeLayout,
    LayoutDocument,
    ManualConfiguration,
    ManualConfigurationRequest,
    Metrics,
    OptimizationRunRequest,
    RunDetail,
    RunSummary,
    SaveLayoutRequest,
    SensorPlacement,
    Solution,
    SolutionDetail,
)
from modules.service import optimization_model as model
from modules.service.optimization_nsga2 import LIBRARY, run_nsga2
from modules.service.optimization_template import template_layout
from shared.errors.problem_details import Problem

RUN_TIMEOUT_SECONDS = 60
_run_slots = asyncio.Semaphore(2)


async def get_layout(home_id: UUID, repository: SupabaseRepository) -> LayoutDocument:
    row = await repository.get_home_layout(home_id)
    if row is None:
        return LayoutDocument(
            home_id=home_id,
            source="template",
            version=0,
            updated_at=None,
            layout=template_layout(),
        )
    return _layout_document(row)


async def save_layout(
    home_id: UUID,
    payload: SaveLayoutRequest,
    actor: UserProfile,
    repository: SupabaseRepository,
) -> LayoutDocument:
    layout = payload.layout.model_dump(mode="json")
    if payload.version == 0:
        row = await repository.create_home_layout(home_id, layout, actor.id)
    else:
        row = await repository.update_home_layout(home_id, layout, payload.version, actor.id)
        if row is None:
            raise Problem(
                409,
                "LAYOUT_VERSION_CONFLICT",
                "Conflito de versão",
                "O layout foi alterado por outra pessoa. Recarregue e aplique suas mudanças "
                "novamente.",
            )
    return _layout_document(row)


async def evaluate_configuration(
    home_id: UUID,
    payload: EvaluationRequest,
    repository: SupabaseRepository,
) -> Evaluation:
    layout, version = await _saved_layout(home_id, repository)
    compiled = _compile(layout)
    return _evaluation(compiled, payload.sensors, version)


async def run_optimization(
    home_id: UUID,
    payload: OptimizationRunRequest,
    actor: UserProfile,
    repository: SupabaseRepository,
) -> RunDetail:
    layout, version = await _saved_layout(home_id, repository)
    compiled = _compile(layout)
    seed = payload.seed if payload.seed is not None else secrets.randbelow(2**31)
    if _run_slots.locked():
        raise Problem(
            503,
            "OPTIMIZATION_BUSY",
            "Otimizador ocupado",
            "Há otimizações em andamento. Tente novamente em instantes.",
            headers={"Retry-After": "10"},
        )
    async with _run_slots:
        try:
            outcome = await asyncio.wait_for(
                asyncio.to_thread(
                    run_nsga2,
                    compiled,
                    population_size=payload.population_size,
                    generations=payload.generations,
                    seed=seed,
                ),
                timeout=RUN_TIMEOUT_SECONDS,
            )
        except TimeoutError as exc:
            raise Problem(
                503,
                "OPTIMIZATION_TIMEOUT",
                "Otimização interrompida",
                "A otimização excedeu o tempo limite. Reduza população ou gerações.",
            ) from exc

    run_id = uuid4()
    solutions = []
    for index, vector in enumerate(outcome.solutions):
        result = model.evaluate(compiled, vector)
        solutions.append(
            Solution(
                id=uuid4(),
                index=index,
                sensors=model.decode(compiled, vector),
                metrics=result.metrics,
            )
        )
    run_row = {
        "id": str(run_id),
        "home_id": str(home_id),
        "created_by": str(actor.id),
        "layout_version": version,
        "layout_snapshot": layout.model_dump(mode="json"),
        "library": LIBRARY,
        "population_size": payload.population_size,
        "generations": payload.generations,
        "seed": seed,
        "evaluations": outcome.evaluations,
        "duration_ms": outcome.duration_ms,
        "status": "completed" if solutions else "no_feasible_solution",
    }
    await repository.create_optimization_run(
        run_row,
        [
            {
                "id": str(solution.id),
                "solution_index": solution.index,
                "sensors": [sensor.model_dump() for sensor in solution.sensors],
                "coverage": solution.metrics.coverage,
                "cost": solution.metrics.cost,
                "vulnerability": solution.metrics.vulnerability,
                "sensors_by_type": solution.metrics.sensors_by_type,
            }
            for solution in solutions
        ],
    )
    stored = await repository.get_optimization_run(home_id, run_id)
    if stored is None:
        raise Problem(
            503,
            "INVALID_DATABASE_RESPONSE",
            "Serviço temporariamente indisponível",
            "O banco não confirmou a gravação da otimização.",
        )
    return RunDetail(**_run_summary(stored).model_dump(), layout=layout, solutions=solutions)


async def list_runs(
    home_id: UUID,
    limit: int,
    offset: int,
    repository: SupabaseRepository,
) -> list[RunSummary]:
    rows = await repository.list_optimization_runs(home_id, limit=limit, offset=offset)
    return [_run_summary(row) for row in rows]


async def get_run(home_id: UUID, run_id: UUID, repository: SupabaseRepository) -> RunDetail:
    row = await _run_row(home_id, run_id, repository)
    solutions = await repository.list_optimization_solutions(run_id)
    return RunDetail(
        **_run_summary(row).model_dump(),
        layout=_snapshot(row),
        solutions=[_solution(item) for item in solutions],
    )


async def get_solution(
    home_id: UUID,
    run_id: UUID,
    solution_id: UUID,
    repository: SupabaseRepository,
) -> SolutionDetail:
    row = await _run_row(home_id, run_id, repository)
    item = await repository.get_optimization_solution(run_id, solution_id)
    if item is None:
        raise Problem(
            404,
            "SOLUTION_NOT_FOUND",
            "Não encontrada",
            "A solução não existe nesta otimização.",
        )
    solution = _solution(item)
    compiled = _compile(_snapshot(row))
    result = model.evaluate(compiled, model.encode(compiled, solution.sensors))
    return SolutionDetail(**solution.model_dump(), run_id=run_id, points=result.points)


async def compare(
    home_id: UUID,
    run_id: UUID,
    payload: CompareRequest,
    repository: SupabaseRepository,
) -> Comparison:
    row = await _run_row(home_id, run_id, repository)
    if payload.manual_configuration_id is not None:
        saved = await _manual_row(home_id, payload.manual_configuration_id, repository)
        sensors = _placements(saved["sensors"])
    else:
        sensors = payload.sensors or []
    compiled = _compile(_snapshot(row))
    manual = _evaluation(compiled, sensors, int(row["layout_version"]))
    entries = []
    for item in await repository.list_optimization_solutions(run_id):
        solution = _solution(item)
        entries.append(_comparison_entry(solution, manual.metrics))
    return Comparison(
        run_id=run_id,
        manual=manual,
        manual_is_dominated=any(entry.solution_dominates_manual for entry in entries),
        entries=entries,
    )


async def create_manual_configuration(
    home_id: UUID,
    payload: ManualConfigurationRequest,
    actor: UserProfile,
    repository: SupabaseRepository,
) -> ManualConfiguration:
    layout, version = await _saved_layout(home_id, repository)
    try:
        model.encode(_structure_only(layout), payload.sensors)
    except model.InvalidPlacementError as exc:
        raise _invalid_placement(str(exc)) from exc
    row = await repository.create_manual_configuration(
        home_id,
        payload.name,
        [sensor.model_dump() for sensor in payload.sensors],
        actor.id,
    )
    return _manual_configuration(row, layout, version)


async def list_manual_configurations(
    home_id: UUID,
    repository: SupabaseRepository,
) -> list[ManualConfiguration]:
    rows = await repository.list_manual_configurations(home_id)
    saved = await repository.get_home_layout(home_id)
    layout = HomeLayout.model_validate(saved["layout"]) if saved else None
    version = int(saved["version"]) if saved else 0
    return [_manual_configuration(row, layout, version) for row in rows]


async def delete_manual_configuration(
    home_id: UUID,
    configuration_id: UUID,
    repository: SupabaseRepository,
) -> None:
    if not await repository.delete_manual_configuration(home_id, configuration_id):
        raise _manual_not_found()


def _comparison_entry(solution: Solution, manual: Metrics) -> ComparisonEntry:
    metrics = solution.metrics
    return ComparisonEntry(
        solution_id=solution.id,
        index=solution.index,
        metrics=metrics,
        delta_coverage=round(metrics.coverage - manual.coverage, 9),
        delta_cost=round(metrics.cost - manual.cost, 9),
        delta_vulnerability=round(metrics.vulnerability - manual.vulnerability, 9),
        solution_dominates_manual=model.dominates(metrics, manual),
        manual_dominates_solution=model.dominates(manual, metrics),
    )


def _manual_configuration(
    row: dict[str, Any],
    layout: HomeLayout | None,
    version: int,
) -> ManualConfiguration:
    sensors = _placements(row["sensors"])
    evaluation = None
    error = None
    if layout is None:
        error = "Não há layout salvo para esta residência."
    else:
        try:
            evaluation = _evaluation(model.compile_layout(layout), sensors, version)
        except model.LayoutIncompleteError as exc:
            error = "Layout incompleto: " + ", ".join(exc.missing)
        except Problem as exc:
            error = exc.detail
    return ManualConfiguration(
        id=row["id"],
        home_id=row["home_id"],
        name=row["name"],
        sensors=sensors,
        created_at=row["created_at"],
        created_by=row.get("created_by"),
        evaluation=evaluation,
        evaluation_error=error,
    )


def _evaluation(
    compiled: model.CompiledLayout,
    sensors: list[SensorPlacement],
    version: int,
) -> Evaluation:
    try:
        vector = model.encode(compiled, sensors)
    except model.InvalidPlacementError as exc:
        raise _invalid_placement(str(exc)) from exc
    result = model.evaluate(compiled, vector)
    return Evaluation(
        layout_version=version,
        metrics=result.metrics,
        feasible=result.feasible,
        violations=result.violations,
        points=result.points,
    )


def _compile(layout: HomeLayout) -> model.CompiledLayout:
    try:
        return model.compile_layout(layout)
    except model.LayoutIncompleteError as exc:
        raise Problem(
            409,
            "LAYOUT_INCOMPLETE",
            "Layout incompleto",
            "Preencha antes de calcular: " + ", ".join(exc.missing) + ".",
        ) from exc


def _structure_only(layout: HomeLayout) -> model.CompiledLayout:
    """Compila apenas a estrutura (ids), mesmo com custos ainda vazios."""
    filled = layout.model_copy(
        update={
            "budget": layout.budget or 0,
            "sensor_types": [
                sensor_type.model_copy(
                    update={
                        "unit_cost": sensor_type.unit_cost or 0,
                        "installation_cost": sensor_type.installation_cost or 0,
                    }
                )
                for sensor_type in layout.sensor_types
            ],
        }
    )
    return model.compile_layout(filled)


async def _saved_layout(
    home_id: UUID,
    repository: SupabaseRepository,
) -> tuple[HomeLayout, int]:
    row = await repository.get_home_layout(home_id)
    if row is None:
        raise Problem(
            409,
            "LAYOUT_REQUIRED",
            "Layout não salvo",
            "Revise e salve o layout da residência antes de avaliar ou otimizar.",
        )
    document = _layout_document(row)
    return document.layout, document.version


def _layout_document(row: dict[str, Any]) -> LayoutDocument:
    try:
        return LayoutDocument(
            home_id=row["home_id"],
            source="saved",
            version=int(row["version"]),
            updated_at=row.get("updated_at"),
            layout=HomeLayout.model_validate(row["layout"]),
        )
    except (KeyError, ValueError, ValidationError) as exc:
        raise _invalid_stored_data() from exc


async def _run_row(
    home_id: UUID,
    run_id: UUID,
    repository: SupabaseRepository,
) -> dict[str, Any]:
    row = await repository.get_optimization_run(home_id, run_id)
    if row is None:
        raise Problem(
            404,
            "OPTIMIZATION_RUN_NOT_FOUND",
            "Não encontrada",
            "A otimização não existe nesta residência.",
        )
    return row


async def _manual_row(
    home_id: UUID,
    configuration_id: UUID,
    repository: SupabaseRepository,
) -> dict[str, Any]:
    row = await repository.get_manual_configuration(home_id, configuration_id)
    if row is None:
        raise _manual_not_found()
    return row


def _run_summary(row: dict[str, Any]) -> RunSummary:
    try:
        return RunSummary.model_validate(
            {key: value for key, value in row.items() if key != "layout_snapshot"}
        )
    except ValidationError as exc:
        raise _invalid_stored_data() from exc


def _snapshot(row: dict[str, Any]) -> HomeLayout:
    try:
        return HomeLayout.model_validate(row["layout_snapshot"])
    except (KeyError, ValidationError) as exc:
        raise _invalid_stored_data() from exc


def _solution(row: dict[str, Any]) -> Solution:
    try:
        sensors = _placements(row["sensors"])
        by_type = {str(key): int(value) for key, value in row["sensors_by_type"].items()}
        return Solution(
            id=row["id"],
            index=int(row["solution_index"]),
            sensors=sensors,
            metrics=Metrics(
                coverage=float(row["coverage"]),
                cost=float(row["cost"]),
                vulnerability=float(row["vulnerability"]),
                sensor_count=len(sensors),
                sensors_by_type=by_type,
            ),
        )
    except (KeyError, ValueError, TypeError, AttributeError, ValidationError) as exc:
        raise _invalid_stored_data() from exc


def _placements(value: Any) -> list[SensorPlacement]:
    try:
        return [SensorPlacement.model_validate(item) for item in value]
    except (TypeError, ValidationError) as exc:
        raise _invalid_stored_data() from exc


def _invalid_placement(detail: str) -> Problem:
    return Problem(422, "INVALID_SENSOR_PLACEMENT", "Posição de sensor inválida", detail)


def _manual_not_found() -> Problem:
    return Problem(
        404,
        "MANUAL_CONFIGURATION_NOT_FOUND",
        "Não encontrada",
        "A configuração manual não existe nesta residência.",
    )


def _invalid_stored_data() -> Problem:
    return Problem(
        503,
        "INVALID_DATABASE_RESPONSE",
        "Serviço temporariamente indisponível",
        "Os dados de otimização armazenados estão incompletos ou inválidos.",
    )
