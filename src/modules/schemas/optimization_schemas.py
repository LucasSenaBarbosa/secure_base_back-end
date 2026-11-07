from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_ROOMS = 50
MAX_CRITICAL_POINTS = 300
MAX_CANDIDATE_POINTS = 200
MAX_SENSOR_TYPES = 20
MAX_GENES = 1000

ElementId = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,47}$")]
Coordinate = Annotated[float, Field(ge=-50, le=50)]
Position = tuple[Coordinate, Coordinate, Coordinate]
Name = Annotated[str, Field(min_length=1, max_length=80)]
Money = Annotated[float, Field(ge=0, le=10_000_000)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SensorType(_Strict):
    id: ElementId
    name: Name
    unit_cost: Money | None = Field(
        default=None,
        description="Custo de aquisição por unidade. Obrigatório para avaliar ou otimizar.",
    )
    installation_cost: Money | None = Field(
        default=None,
        description="Custo de instalação por unidade. Obrigatório para avaliar ou otimizar.",
    )
    stock: int = Field(ge=0, le=1000, description="Quantidade disponível.")
    range: float = Field(gt=0, le=50, description="Alcance, em unidades da maquete.")
    field_of_view_deg: float = Field(
        gt=0,
        le=360,
        description="Abertura horizontal do campo de detecção; 360 = omnidirecional.",
    )
    reliability: float = Field(
        default=1.0,
        gt=0,
        le=1,
        description="Probabilidade de detecção de um ponto dentro do alcance e do campo.",
    )


class Room(_Strict):
    id: ElementId
    name: Name
    glb_node: str | None = Field(default=None, max_length=80)
    floor_y: Coordinate
    height: float = Field(gt=0, le=50)
    min_xz: tuple[Coordinate, Coordinate]
    max_xz: tuple[Coordinate, Coordinate]
    visible_room_ids: list[ElementId] = Field(
        default_factory=list,
        max_length=MAX_ROOMS,
        description="Ambientes cujos pontos são visíveis por sensores instalados neste.",
    )

    @model_validator(mode="after")
    def validate_bounds(self) -> "Room":
        if self.min_xz[0] >= self.max_xz[0] or self.min_xz[1] >= self.max_xz[1]:
            raise ValueError("min_xz deve ser menor que max_xz nos dois eixos.")
        if self.id in self.visible_room_ids:
            raise ValueError("Um ambiente não pode listar a si mesmo em visible_room_ids.")
        return self


class CriticalPoint(_Strict):
    id: ElementId
    name: Name
    room_id: ElementId
    position: Position
    importance: int = Field(ge=1, le=5)


class CandidatePoint(_Strict):
    id: ElementId
    name: Name
    room_id: ElementId
    position: Position
    allowed_sensor_type_ids: list[ElementId] = Field(min_length=1, max_length=MAX_SENSOR_TYPES)
    extra_installation_cost: Money = 0
    direction: Position | None = Field(
        default=None,
        description=(
            "Direção do sensor direcional. Quando ausente, aponta para o centro do ambiente."
        ),
    )


class HomeLayout(_Strict):
    budget: Money | None = Field(
        default=None,
        description="Orçamento máximo. Obrigatório para avaliar ou otimizar.",
    )
    coverage_threshold: float = Field(
        default=0.8,
        gt=0,
        le=1,
        description="Probabilidade mínima de detecção para um ponto contar como coberto.",
    )
    rooms: list[Room] = Field(min_length=1, max_length=MAX_ROOMS)
    critical_points: list[CriticalPoint] = Field(min_length=1, max_length=MAX_CRITICAL_POINTS)
    candidate_points: list[CandidatePoint] = Field(min_length=1, max_length=MAX_CANDIDATE_POINTS)
    sensor_types: list[SensorType] = Field(min_length=1, max_length=MAX_SENSOR_TYPES)

    @model_validator(mode="after")
    def validate_references(self) -> "HomeLayout":
        for label, items in (
            ("rooms", self.rooms),
            ("critical_points", self.critical_points),
            ("candidate_points", self.candidate_points),
            ("sensor_types", self.sensor_types),
        ):
            ids = [item.id for item in items]
            if len(ids) != len(set(ids)):
                raise ValueError(f"{label} contém ids repetidos.")
        room_ids = {room.id for room in self.rooms}
        type_ids = {sensor_type.id for sensor_type in self.sensor_types}
        for room in self.rooms:
            unknown = set(room.visible_room_ids) - room_ids
            if unknown:
                raise ValueError(f"Ambiente {room.id} referencia ambientes inexistentes.")
        for point in [*self.critical_points, *self.candidate_points]:
            if point.room_id not in room_ids:
                raise ValueError(f"Ponto {point.id} referencia ambiente inexistente.")
        genes = 0
        for candidate in self.candidate_points:
            allowed = candidate.allowed_sensor_type_ids
            if len(allowed) != len(set(allowed)):
                raise ValueError(f"Candidato {candidate.id} repete tipos permitidos.")
            if set(allowed) - type_ids:
                raise ValueError(f"Candidato {candidate.id} referencia tipo inexistente.")
            genes += len(allowed)
        if genes > MAX_GENES:
            raise ValueError(
                f"A combinação de candidatos e tipos excede {MAX_GENES} posições possíveis."
            )
        return self


class LayoutDocument(BaseModel):
    home_id: UUID
    source: Literal["saved", "template"]
    version: int
    updated_at: datetime | None
    layout: HomeLayout


class SaveLayoutRequest(_Strict):
    version: int = Field(
        ge=0,
        description="Versão lida antes da edição; use 0 para salvar pela primeira vez.",
    )
    layout: HomeLayout


class SensorPlacement(_Strict):
    candidate_id: ElementId
    sensor_type_id: ElementId


Placements = Annotated[list[SensorPlacement], Field(max_length=MAX_CANDIDATE_POINTS)]


def _unique_candidates(placements: list[SensorPlacement]) -> list[SensorPlacement]:
    candidates = [placement.candidate_id for placement in placements]
    if len(candidates) != len(set(candidates)):
        raise ValueError("Cada ponto candidato aceita no máximo um sensor.")
    return placements


class Metrics(BaseModel):
    coverage: float = Field(description="Fração dos pontos críticos cobertos (0–1).")
    cost: float = Field(description="Custo total: aquisição + instalação.")
    vulnerability: float = Field(
        description="Vulnerabilidade residual ponderada pela importância (0–1).",
    )
    sensor_count: int
    sensors_by_type: dict[str, int]


class Violation(BaseModel):
    code: Literal["BUDGET_EXCEEDED", "STOCK_EXCEEDED"]
    detail: str


class PointCoverage(BaseModel):
    critical_point_id: str
    detection_probability: float
    covered: bool


class EvaluationRequest(_Strict):
    sensors: Placements

    _check = field_validator("sensors")(_unique_candidates)


class Evaluation(BaseModel):
    layout_version: int
    metrics: Metrics
    feasible: bool
    violations: list[Violation]
    points: list[PointCoverage]


class OptimizationRunRequest(_Strict):
    population_size: int = Field(default=60, ge=10, le=200)
    generations: int = Field(default=100, ge=1, le=300)
    seed: int | None = Field(
        default=None,
        ge=0,
        le=2**31 - 1,
        description="Semente para reprodutibilidade; gerada e retornada quando ausente.",
    )


class Solution(BaseModel):
    id: UUID
    index: int
    sensors: list[SensorPlacement]
    metrics: Metrics


class SolutionDetail(Solution):
    run_id: UUID
    points: list[PointCoverage]


class RunSummary(BaseModel):
    id: UUID
    home_id: UUID
    created_at: datetime
    created_by: UUID | None
    layout_version: int
    algorithm: Literal["NSGA-II"] = "NSGA-II"
    library: str
    population_size: int
    generations: int
    seed: int
    evaluations: int
    duration_ms: int
    status: Literal["completed", "no_feasible_solution"]
    solution_count: int


class RunDetail(RunSummary):
    layout: HomeLayout
    solutions: list[Solution]


class ManualConfigurationRequest(_Strict):
    name: str = Field(min_length=1, max_length=120)
    sensors: Placements

    _check = field_validator("sensors")(_unique_candidates)

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


class ManualConfiguration(BaseModel):
    id: UUID
    home_id: UUID
    name: str
    sensors: list[SensorPlacement]
    created_at: datetime
    created_by: UUID | None
    evaluation: Evaluation | None = Field(
        description="Métricas calculadas contra o layout salvo atual.",
    )
    evaluation_error: str | None = Field(
        default=None,
        description="Motivo de não haver avaliação (layout incompleto ou ponto removido).",
    )


class CompareRequest(_Strict):
    manual_configuration_id: UUID | None = None
    sensors: Placements | None = None

    _check = field_validator("sensors")(
        lambda value: _unique_candidates(value) if value is not None else value
    )

    @model_validator(mode="after")
    def exactly_one_source(self) -> "CompareRequest":
        if (self.manual_configuration_id is None) == (self.sensors is None):
            raise ValueError("Informe manual_configuration_id ou sensors, não ambos.")
        return self


class ComparisonEntry(BaseModel):
    solution_id: UUID
    index: int
    metrics: Metrics
    delta_coverage: float = Field(description="Solução − manual.")
    delta_cost: float = Field(description="Solução − manual.")
    delta_vulnerability: float = Field(description="Solução − manual.")
    solution_dominates_manual: bool
    manual_dominates_solution: bool


class Comparison(BaseModel):
    run_id: UUID
    manual: Evaluation
    manual_is_dominated: bool = Field(
        description="Verdadeiro se ao menos uma solução calculada domina a configuração manual.",
    )
    entries: list[ComparisonEntry]
