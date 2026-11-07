import itertools
import math

import numpy as np
import pytest
from pydantic import ValidationError

from modules.schemas.optimization_schemas import (
    CompareRequest,
    EvaluationRequest,
    HomeLayout,
    Metrics,
    SensorPlacement,
)
from modules.service import optimization_model as model
from modules.service.optimization_nsga2 import pareto_front, run_nsga2
from modules.service.optimization_template import TEMPLATE_LAYOUT, template_layout


def small_layout(**overrides: object) -> dict:
    layout = {
        "budget": 20,
        "coverage_threshold": 0.4,
        "rooms": [
            {"id": "a", "name": "A", "floor_y": 0, "height": 1,
             "min_xz": [0, 0], "max_xz": [2, 2]},
            {"id": "b", "name": "B", "floor_y": 0, "height": 1,
             "min_xz": [2, 0], "max_xz": [4, 2]},
        ],
        "critical_points": [
            {"id": "p1", "name": "P1", "room_id": "a", "position": [1, 0, 1], "importance": 3},
            {"id": "p2", "name": "P2", "room_id": "a", "position": [1.9, 0, 1.9],
             "importance": 1},
            {"id": "p3", "name": "P3", "room_id": "b", "position": [3, 0, 1], "importance": 2},
        ],
        "candidate_points": [
            {"id": "c1", "name": "C1", "room_id": "a", "position": [0, 0, 0],
             "allowed_sensor_type_ids": ["pir", "contact"]},
            {"id": "c2", "name": "C2", "room_id": "b", "position": [3, 0, 1.1],
             "allowed_sensor_type_ids": ["contact"]},
        ],
        "sensor_types": [
            {"id": "pir", "name": "PIR", "unit_cost": 10, "installation_cost": 5, "stock": 1,
             "range": 2, "field_of_view_deg": 90, "reliability": 0.5},
            {"id": "contact", "name": "Contato", "unit_cost": 3, "installation_cost": 1,
             "stock": 1, "range": 0.2, "field_of_view_deg": 360, "reliability": 1},
        ],
    }
    layout.update(overrides)
    return layout


def compiled(**overrides: object) -> model.CompiledLayout:
    return model.compile_layout(HomeLayout.model_validate(small_layout(**overrides)))


def placements(*pairs: tuple[str, str]) -> list[SensorPlacement]:
    return [SensorPlacement(candidate_id=c, sensor_type_id=t) for c, t in pairs]


def test_metrics_match_hand_calculation() -> None:
    layout = compiled()
    chosen = placements(("c1", "pir"), ("c2", "contact"))
    result = model.evaluate(layout, model.encode(layout, chosen))

    # p1: PIR a √2 do candidato, dentro do cone → 0,5; p2: fora do alcance;
    # p3: contato a 0,1 → 1. Coberto se ≥ 0,4.
    assert [p.detection_probability for p in result.points] == [0.5, 0.0, 1.0]
    assert [p.covered for p in result.points] == [True, False, True]
    assert result.metrics.coverage == pytest.approx(2 / 3)
    assert result.metrics.cost == 19
    assert result.metrics.vulnerability == pytest.approx((3 * 0.5 + 1 * 1 + 2 * 0) / 6)
    assert result.metrics.sensors_by_type == {"pir": 1, "contact": 1}
    assert result.feasible and result.violations == []


def test_empty_configuration_has_full_vulnerability_and_no_cost() -> None:
    layout = compiled()
    result = model.evaluate(layout, model.encode(layout, []))

    assert result.metrics.coverage == 0
    assert result.metrics.cost == 0
    assert result.metrics.vulnerability == 1
    assert result.feasible


def test_independent_detections_combine_probabilistically() -> None:
    layout = compiled(
        candidate_points=[
            {"id": "c1", "name": "C1", "room_id": "a", "position": [0, 0, 0],
             "allowed_sensor_type_ids": ["pir"]},
            {"id": "c3", "name": "C3", "room_id": "a", "position": [2, 0, 2],
             "allowed_sensor_type_ids": ["pir"]},
        ],
    )
    detected = model.point_detection(layout, np.array([True, True]))[0]

    assert detected[0] == pytest.approx(1 - 0.5 * 0.5)


def test_field_of_view_and_range_limit_detection() -> None:
    away = compiled(
        candidate_points=[
            {"id": "c1", "name": "C1", "room_id": "a", "position": [0, 0, 0],
             "allowed_sensor_type_ids": ["pir"], "direction": [-1, 0, -1]},
        ],
    )
    short = compiled(
        sensor_types=[
            {"id": "pir", "name": "PIR", "unit_cost": 1, "installation_cost": 0, "stock": 1,
             "range": 1.0, "field_of_view_deg": 90},
            {"id": "contact", "name": "Contato", "unit_cost": 1, "installation_cost": 0,
             "stock": 1, "range": 0.2, "field_of_view_deg": 360},
        ],
    )

    assert away.detection[0].tolist() == [0, 0, 0]
    assert short.detection[short.gene_index[("c1", "pir")]].tolist() == [0, 0, 0]


def test_visibility_between_rooms_is_explicit() -> None:
    sensor_types = [
        {"id": "pir", "name": "PIR", "unit_cost": 1, "installation_cost": 0, "stock": 1,
         "range": 10, "field_of_view_deg": 360},
        {"id": "contact", "name": "Contato", "unit_cost": 1, "installation_cost": 0,
         "stock": 1, "range": 0.2, "field_of_view_deg": 360},
    ]
    closed = compiled(sensor_types=sensor_types)
    rooms = small_layout()["rooms"]
    rooms[0] = {**rooms[0], "visible_room_ids": ["b"]}
    open_plan = compiled(sensor_types=sensor_types, rooms=rooms)

    gene = closed.gene_index[("c1", "pir")]
    assert closed.detection[gene][2] == 0
    assert open_plan.detection[gene][2] == 1


def test_budget_and_stock_violations_are_reported() -> None:
    over_budget = compiled(budget=18)
    no_stock = compiled(
        sensor_types=[
            {**small_layout()["sensor_types"][0], "stock": 0},
            small_layout()["sensor_types"][1],
        ],
    )
    chosen = placements(("c1", "pir"), ("c2", "contact"))

    budget_result = model.evaluate(over_budget, model.encode(over_budget, chosen))
    stock_result = model.evaluate(no_stock, model.encode(no_stock, chosen))

    assert not budget_result.feasible
    assert [v.code for v in budget_result.violations] == ["BUDGET_EXCEEDED"]
    assert not stock_result.feasible
    assert [v.code for v in stock_result.violations] == ["STOCK_EXCEEDED"]


def test_constraint_matrix_follows_g_less_or_equal_zero_convention() -> None:
    layout = compiled(budget=18)
    values = model.constraints(layout, model.encode(layout, placements(("c1", "pir"))))

    assert values.tolist() == [[15 - 18, 1 - 1, 0 - 1]]


def test_disallowed_or_unknown_placement_is_rejected() -> None:
    layout = compiled()

    with pytest.raises(model.InvalidPlacementError):
        model.encode(layout, placements(("c2", "pir")))
    with pytest.raises(model.InvalidPlacementError):
        model.encode(layout, placements(("missing", "pir")))


def test_layout_with_missing_costs_or_budget_is_incomplete() -> None:
    with pytest.raises(model.LayoutIncompleteError) as error:
        model.compile_layout(template_layout())

    assert "budget" in error.value.missing
    assert "sensor_types.pir.unit_cost" in error.value.missing


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["rooms"].append(dict(d["rooms"][0])),
        lambda d: d["critical_points"][0].update(room_id="nowhere"),
        lambda d: d["candidate_points"][0].update(allowed_sensor_type_ids=["laser"]),
        lambda d: d["critical_points"][0].update(importance=6),
        lambda d: d["sensor_types"][0].update(stock=-1),
        lambda d: d["rooms"][0].update(min_xz=[3, 0]),
        lambda d: d["rooms"][0].update(visible_room_ids=["a"]),
        lambda d: d.update(unexpected=True),
    ],
)
def test_invalid_layouts_are_rejected(change: object) -> None:
    data = small_layout()
    change(data)  # type: ignore[operator]

    with pytest.raises(ValidationError):
        HomeLayout.model_validate(data)


def test_placement_requests_reject_two_sensors_on_one_candidate() -> None:
    sensors = [
        {"candidate_id": "c1", "sensor_type_id": "pir"},
        {"candidate_id": "c1", "sensor_type_id": "contact"},
    ]

    with pytest.raises(ValidationError):
        EvaluationRequest.model_validate({"sensors": sensors})
    with pytest.raises(ValidationError):
        CompareRequest.model_validate({})


def test_template_layout_is_valid_and_has_no_invented_costs() -> None:
    layout = template_layout()

    assert layout.budget is None
    assert all(t.unit_cost is None and t.installation_cost is None for t in layout.sensor_types)
    assert {room.glb_node for room in layout.rooms} >= {"Sala", "Cozinha", "Suite"}
    assert TEMPLATE_LAYOUT["sensor_types"][0]["range"] == 1.75


def test_dominance_requires_strict_improvement() -> None:
    def metrics(coverage: float, cost: float, vulnerability: float) -> Metrics:
        return Metrics(
            coverage=coverage,
            cost=cost,
            vulnerability=vulnerability,
            sensor_count=0,
            sensors_by_type={},
        )

    assert model.dominates(metrics(0.8, 10, 0.2), metrics(0.7, 10, 0.2))
    assert not model.dominates(metrics(0.8, 10, 0.2), metrics(0.8, 10, 0.2))
    assert not model.dominates(metrics(0.9, 12, 0.1), metrics(0.8, 10, 0.2))


def brute_force_front(layout: model.CompiledLayout) -> set[tuple[float, float, float]]:
    vectors = np.array(list(itertools.product([False, True], repeat=layout.n_genes)))
    feasible = vectors[model.is_feasible(layout, vectors)]
    values = model.objectives(layout, feasible)
    front = set()
    for i, (cov, cost, vul) in enumerate(values):
        dominated = any(
            c >= cov and k <= cost and v <= vul and (c > cov or k < cost or v < vul)
            for j, (c, k, v) in enumerate(values)
            if j != i
        )
        if not dominated:
            front.add((round(cov, 9), round(cost, 9), round(vul, 9)))
    return front


def richer_layout() -> model.CompiledLayout:
    data = small_layout(budget=25)
    data["sensor_types"][0]["stock"] = 2
    data["sensor_types"][1]["stock"] = 2
    data["candidate_points"].append(
        {"id": "c3", "name": "C3", "room_id": "a", "position": [2, 0, 2],
         "allowed_sensor_type_ids": ["pir", "contact"]}
    )
    data["candidate_points"].append(
        {"id": "c4", "name": "C4", "room_id": "a", "position": [1.9, 0, 1.95],
         "allowed_sensor_type_ids": ["contact"], "extra_installation_cost": 2}
    )
    return model.compile_layout(HomeLayout.model_validate(data))


def test_nsga2_returns_feasible_mutually_non_dominated_solutions() -> None:
    layout = richer_layout()
    outcome = run_nsga2(layout, population_size=30, generations=40, seed=11)
    population = np.array(outcome.solutions)

    assert outcome.solutions
    assert model.is_feasible(layout, population).all()
    assert model.one_sensor_per_candidate(layout, population).all()
    values = model.objectives(layout, population)
    assert (values[:, 1] <= layout.budget + 1e-9).all()
    for i, j in itertools.permutations(range(len(values)), 2):
        a, b = values[i], values[j]
        assert not (
            a[0] >= b[0] and a[1] <= b[1] and a[2] <= b[2]
            and (a[0] > b[0] or a[1] < b[1] or a[2] < b[2])
        )


def test_nsga2_finds_the_exact_front_of_a_small_instance() -> None:
    layout = richer_layout()
    outcome = run_nsga2(layout, population_size=40, generations=60, seed=3)
    found = {
        tuple(round(float(v), 9) for v in row)
        for row in model.objectives(layout, np.array(outcome.solutions))
    }

    assert found == brute_force_front(layout)


def test_nsga2_is_reproducible_with_the_same_seed() -> None:
    layout = richer_layout()
    first = run_nsga2(layout, population_size=20, generations=15, seed=5)
    second = run_nsga2(layout, population_size=20, generations=15, seed=5)

    assert len(first.solutions) == len(second.solutions)
    assert all((a == b).all() for a, b in zip(first.solutions, second.solutions, strict=True))
    assert first.evaluations == second.evaluations


def test_pareto_front_discards_infeasible_individuals() -> None:
    layout = compiled(budget=3)
    population = np.array([[True, False, True], [False, False, False]])

    front = pareto_front(layout, population)

    assert len(front) == 1
    assert not front[0].any()
    assert math.isclose(model.objectives(layout, front[0])[0][2], 1.0)
