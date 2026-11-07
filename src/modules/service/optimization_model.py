"""Modelo matemático da alocação de sensores.

Funções puras, sem acesso a banco ou HTTP. Os mesmos cálculos são usados pelo
NSGA-II, pela avaliação de configurações manuais e pela comparação entre elas,
para que todas as métricas exibidas venham da mesma definição.
"""

import math
from dataclasses import dataclass

import numpy as np

from modules.schemas.optimization_schemas import (
    CandidatePoint,
    CriticalPoint,
    HomeLayout,
    Metrics,
    PointCoverage,
    Room,
    SensorPlacement,
    SensorType,
    Violation,
)

FEASIBILITY_TOLERANCE = 1e-9
_ROUND = 9
_MAX_DETECTION = 1 - 1e-15


class LayoutIncompleteError(ValueError):
    def __init__(self, missing: list[str]):
        super().__init__("Layout incompleto: " + ", ".join(missing))
        self.missing = missing


class InvalidPlacementError(ValueError):
    pass


@dataclass(frozen=True)
class CompiledLayout:
    """Layout convertido em matrizes para avaliação vetorizada.

    Cada gene representa um par (ponto candidato, tipo de sensor permitido).
    """

    layout: HomeLayout
    gene_candidate: np.ndarray
    gene_type: np.ndarray
    gene_cost: np.ndarray
    detection: np.ndarray
    log_miss: np.ndarray
    importance: np.ndarray
    stock: np.ndarray
    budget: float
    threshold: float
    gene_index: dict[tuple[str, str], int]

    @property
    def n_genes(self) -> int:
        return int(self.gene_candidate.shape[0])

    @property
    def n_types(self) -> int:
        return len(self.layout.sensor_types)


@dataclass(frozen=True)
class EvaluationResult:
    metrics: Metrics
    feasible: bool
    violations: list[Violation]
    points: list[PointCoverage]


def missing_inputs(layout: HomeLayout) -> list[str]:
    """Campos obrigatórios para calcular custo e restrições que ainda estão vazios."""
    missing = []
    if layout.budget is None:
        missing.append("budget")
    used_types = {
        type_id
        for candidate in layout.candidate_points
        for type_id in candidate.allowed_sensor_type_ids
    }
    for sensor_type in layout.sensor_types:
        if sensor_type.id not in used_types:
            continue
        if sensor_type.unit_cost is None:
            missing.append(f"sensor_types.{sensor_type.id}.unit_cost")
        if sensor_type.installation_cost is None:
            missing.append(f"sensor_types.{sensor_type.id}.installation_cost")
    return missing


def detection_probability(
    sensor_type: SensorType,
    candidate: CandidatePoint,
    point: CriticalPoint,
    rooms: dict[str, Room],
) -> float:
    """Probabilidade de um sensor no candidato detectar um evento no ponto crítico.

    Vale ``reliability`` quando o ponto (1) está no mesmo ambiente do sensor ou
    em um ambiente visível a partir dele, (2) está a uma distância euclidiana
    3D até ``range`` e (3) está dentro da abertura horizontal do sensor.
    Caso contrário, vale 0.
    """
    sensor_room = rooms[candidate.room_id]
    if point.room_id != candidate.room_id and point.room_id not in sensor_room.visible_room_ids:
        return 0.0
    offset = np.subtract(point.position, candidate.position)
    if float(np.linalg.norm(offset)) > sensor_type.range + FEASIBILITY_TOLERANCE:
        return 0.0
    if sensor_type.field_of_view_deg < 360:
        heading = _heading(candidate, sensor_room)
        horizontal = np.array([offset[0], offset[2]])
        distance = float(np.linalg.norm(horizontal))
        if heading is not None and distance > 1e-9:
            cosine = float(np.dot(horizontal, heading) / distance)
            angle = math.degrees(math.acos(max(-1.0, min(1.0, cosine))))
            if angle > sensor_type.field_of_view_deg / 2 + 1e-9:
                return 0.0
    return sensor_type.reliability


def _heading(candidate: CandidatePoint, room: Room) -> np.ndarray | None:
    if candidate.direction is not None:
        vector = np.array([candidate.direction[0], candidate.direction[2]])
    else:
        center = (
            (room.min_xz[0] + room.max_xz[0]) / 2,
            (room.min_xz[1] + room.max_xz[1]) / 2,
        )
        vector = np.array([center[0] - candidate.position[0], center[1] - candidate.position[2]])
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 1e-9 else None


def compile_layout(layout: HomeLayout) -> CompiledLayout:
    missing = missing_inputs(layout)
    if missing:
        raise LayoutIncompleteError(missing)
    rooms = {room.id: room for room in layout.rooms}
    type_position = {sensor_type.id: i for i, sensor_type in enumerate(layout.sensor_types)}
    gene_candidate: list[int] = []
    gene_type: list[int] = []
    gene_cost: list[float] = []
    gene_index: dict[tuple[str, str], int] = {}
    rows: list[list[float]] = []
    for candidate_index, candidate in enumerate(layout.candidate_points):
        for type_id in candidate.allowed_sensor_type_ids:
            sensor_type = layout.sensor_types[type_position[type_id]]
            gene_index[(candidate.id, type_id)] = len(gene_candidate)
            gene_candidate.append(candidate_index)
            gene_type.append(type_position[type_id])
            gene_cost.append(
                float(sensor_type.unit_cost or 0)
                + float(sensor_type.installation_cost or 0)
                + float(candidate.extra_installation_cost)
            )
            rows.append(
                [
                    detection_probability(sensor_type, candidate, point, rooms)
                    for point in layout.critical_points
                ]
            )
    detection = np.array(rows, dtype=float)
    return CompiledLayout(
        layout=layout,
        gene_candidate=np.array(gene_candidate, dtype=int),
        gene_type=np.array(gene_type, dtype=int),
        gene_cost=np.array(gene_cost, dtype=float),
        detection=detection,
        log_miss=np.log1p(-np.minimum(detection, _MAX_DETECTION)),
        importance=np.array([p.importance for p in layout.critical_points], dtype=float),
        stock=np.array([t.stock for t in layout.sensor_types], dtype=float),
        budget=float(layout.budget or 0),
        threshold=layout.coverage_threshold,
        gene_index=gene_index,
    )


def point_detection(compiled: CompiledLayout, population: np.ndarray) -> np.ndarray:
    """``c_j = 1 − Π_s (1 − p_sj)`` para cada indivíduo (linhas) e ponto (colunas)."""
    selected = np.atleast_2d(population).astype(float)
    detected = 1.0 - np.exp(selected @ compiled.log_miss)
    return np.round(np.clip(detected, 0.0, 1.0), 12)


def objectives(compiled: CompiledLayout, population: np.ndarray) -> np.ndarray:
    """Matriz (n, 3): cobertura, custo e vulnerabilidade de cada indivíduo."""
    selected = np.atleast_2d(population).astype(float)
    detected = point_detection(compiled, selected)
    covered = detected >= compiled.threshold - FEASIBILITY_TOLERANCE
    coverage = covered.mean(axis=1)
    cost = selected @ compiled.gene_cost
    vulnerability = ((1.0 - detected) @ compiled.importance) / compiled.importance.sum()
    return np.column_stack([coverage, cost, vulnerability])


def constraints(compiled: CompiledLayout, population: np.ndarray) -> np.ndarray:
    """Restrições ``g ≤ 0``: orçamento e, para cada tipo, estoque."""
    selected = np.atleast_2d(population).astype(float)
    cost = selected @ compiled.gene_cost
    counts = np.zeros((selected.shape[0], compiled.n_types))
    for type_index in range(compiled.n_types):
        counts[:, type_index] = selected[:, compiled.gene_type == type_index].sum(axis=1)
    return np.column_stack([cost - compiled.budget, counts - compiled.stock])


def is_feasible(compiled: CompiledLayout, population: np.ndarray) -> np.ndarray:
    selected = np.atleast_2d(population)
    within_limits = (constraints(compiled, selected) <= FEASIBILITY_TOLERANCE).all(axis=1)
    return within_limits & one_sensor_per_candidate(compiled, selected)


def one_sensor_per_candidate(compiled: CompiledLayout, population: np.ndarray) -> np.ndarray:
    selected = np.atleast_2d(population).astype(int)
    per_candidate = np.zeros((selected.shape[0], len(compiled.layout.candidate_points)))
    np.add.at(per_candidate.T, compiled.gene_candidate, selected.T)
    return (per_candidate <= 1).all(axis=1)


def encode(compiled: CompiledLayout, placements: list[SensorPlacement]) -> np.ndarray:
    vector = np.zeros(compiled.n_genes, dtype=bool)
    for placement in placements:
        key = (placement.candidate_id, placement.sensor_type_id)
        if key not in compiled.gene_index:
            raise InvalidPlacementError(
                f"O tipo {placement.sensor_type_id} não é permitido no ponto "
                f"{placement.candidate_id}, ou um deles não existe no layout."
            )
        vector[compiled.gene_index[key]] = True
    return vector


def decode(compiled: CompiledLayout, vector: np.ndarray) -> list[SensorPlacement]:
    layout = compiled.layout
    return [
        SensorPlacement(
            candidate_id=layout.candidate_points[compiled.gene_candidate[gene]].id,
            sensor_type_id=layout.sensor_types[compiled.gene_type[gene]].id,
        )
        for gene in np.flatnonzero(vector)
    ]


def evaluate(compiled: CompiledLayout, vector: np.ndarray) -> EvaluationResult:
    row = np.atleast_2d(vector)
    coverage, cost, vulnerability = objectives(compiled, row)[0]
    limits = constraints(compiled, row)[0]
    detected = point_detection(compiled, row)[0]
    layout = compiled.layout
    counts = {
        sensor_type.id: int(limits[1 + i] + compiled.stock[i])
        for i, sensor_type in enumerate(layout.sensor_types)
    }
    violations = []
    if limits[0] > FEASIBILITY_TOLERANCE:
        violations.append(
            Violation(
                code="BUDGET_EXCEEDED",
                detail=f"Custo {cost:.2f} excede o orçamento {compiled.budget:.2f}.",
            )
        )
    for i, sensor_type in enumerate(layout.sensor_types):
        if limits[1 + i] > FEASIBILITY_TOLERANCE:
            violations.append(
                Violation(
                    code="STOCK_EXCEEDED",
                    detail=(
                        f"{counts[sensor_type.id]} unidade(s) de {sensor_type.name}; "
                        f"estoque disponível: {sensor_type.stock}."
                    ),
                )
            )
    return EvaluationResult(
        metrics=Metrics(
            coverage=round(float(coverage), _ROUND),
            cost=round(float(cost), _ROUND),
            vulnerability=round(float(vulnerability), _ROUND),
            sensor_count=int(np.count_nonzero(vector)),
            sensors_by_type={key: value for key, value in counts.items() if value},
        ),
        feasible=not violations,
        violations=violations,
        points=[
            PointCoverage(
                critical_point_id=point.id,
                detection_probability=round(float(detected[j]), _ROUND),
                covered=bool(detected[j] >= compiled.threshold - FEASIBILITY_TOLERANCE),
            )
            for j, point in enumerate(layout.critical_points)
        ],
    )


def dominates(a: Metrics, b: Metrics) -> bool:
    """``a`` domina ``b``: não é pior em nenhum objetivo e é melhor em pelo menos um."""
    not_worse = (
        a.coverage >= b.coverage - FEASIBILITY_TOLERANCE
        and a.cost <= b.cost + FEASIBILITY_TOLERANCE
        and a.vulnerability <= b.vulnerability + FEASIBILITY_TOLERANCE
    )
    better = (
        a.coverage > b.coverage + FEASIBILITY_TOLERANCE
        or a.cost < b.cost - FEASIBILITY_TOLERANCE
        or a.vulnerability < b.vulnerability - FEASIBILITY_TOLERANCE
    )
    return not_worse and better
