import copy
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from test_api import FakeGateway, account, app, client
from test_optimization_model import small_layout

from modules.auth.dependencies import get_current_user, get_repository
from modules.schemas.auth_schemas import Role, UserProfile
from shared.errors.problem_details import Problem

PRIMARY = UserProfile(
    id=UUID("b1b1b1b1-b1b1-41b1-81b1-b1b1b1b1b1b1"),
    email="primary@example.com",
    name="Primary",
    role=Role.MEMBER,
)
MEMBER = UserProfile(
    id=UUID("c2c2c2c2-c2c2-42c2-82c2-c2c2c2c2c2c2"),
    email="membro@example.com",
    name="Membro",
    role=Role.MEMBER,
)
OUTSIDER = UserProfile(
    id=UUID("d3d3d3d3-d3d3-43d3-83d3-d3d3d3d3d3d3"),
    email="outra@example.com",
    name="Outra",
    role=Role.MEMBER,
)
RUN = {"population_size": 20, "generations": 20, "seed": 7}


class OptimizationGateway(FakeGateway):
    def __init__(self) -> None:
        super().__init__(accounts=[account()])
        self.layouts: dict[str, dict[str, object]] = {}
        self.runs: dict[str, dict[str, object]] = {}
        self.solutions: dict[str, dict[str, object]] = {}
        self.manual: dict[str, dict[str, object]] = {}

    async def get_home_layout(self, home_id: UUID) -> dict[str, object] | None:
        row = self.layouts.get(str(home_id))
        return copy.deepcopy(row) if row else None

    async def create_home_layout(
        self, home_id: UUID, layout: dict, actor_id: UUID
    ) -> dict[str, object]:
        if str(home_id) in self.layouts:
            raise Problem(409, "LAYOUT_VERSION_CONFLICT", "Conflito de versão", "Conflito.")
        row = {"home_id": str(home_id), "layout": layout, "version": 1, "updated_at": _now()}
        self.layouts[str(home_id)] = row
        return copy.deepcopy(row)

    async def update_home_layout(
        self, home_id: UUID, layout: dict, expected_version: int, actor_id: UUID
    ) -> dict[str, object] | None:
        row = self.layouts.get(str(home_id))
        if row is None or row["version"] != expected_version:
            return None
        row.update(layout=layout, version=expected_version + 1, updated_at=_now())
        return copy.deepcopy(row)

    async def create_optimization_run(self, run: dict, solutions: list[dict]) -> None:
        self.runs[run["id"]] = {**run, "created_at": _now(), "solution_count": len(solutions)}
        for item in solutions:
            self.solutions[item["id"]] = {**item, "run_id": run["id"]}

    async def list_optimization_runs(
        self, home_id: UUID, *, limit: int, offset: int
    ) -> list[dict[str, object]]:
        rows = [
            {k: v for k, v in run.items() if k != "layout_snapshot"}
            for run in self.runs.values()
            if run["home_id"] == str(home_id)
        ]
        return rows[offset : offset + limit]

    async def get_optimization_run(
        self, home_id: UUID, run_id: UUID
    ) -> dict[str, object] | None:
        run = self.runs.get(str(run_id))
        return copy.deepcopy(run) if run and run["home_id"] == str(home_id) else None

    async def list_optimization_solutions(self, run_id: UUID) -> list[dict[str, object]]:
        rows = [s for s in self.solutions.values() if s["run_id"] == str(run_id)]
        return sorted(rows, key=lambda s: s["solution_index"])

    async def get_optimization_solution(
        self, run_id: UUID, solution_id: UUID
    ) -> dict[str, object] | None:
        row = self.solutions.get(str(solution_id))
        return row if row and row["run_id"] == str(run_id) else None

    async def create_manual_configuration(
        self, home_id: UUID, name: str, sensors: list, actor_id: UUID
    ) -> dict[str, object]:
        row = {
            "id": str(uuid4()),
            "home_id": str(home_id),
            "name": name,
            "sensors": sensors,
            "created_by": str(actor_id),
            "created_at": _now(),
        }
        self.manual[row["id"]] = row
        return row

    async def list_manual_configurations(self, home_id: UUID) -> list[dict[str, object]]:
        return [row for row in self.manual.values() if row["home_id"] == str(home_id)]

    async def get_manual_configuration(
        self, home_id: UUID, configuration_id: UUID
    ) -> dict[str, object] | None:
        row = self.manual.get(str(configuration_id))
        return row if row and row["home_id"] == str(home_id) else None

    async def delete_manual_configuration(
        self, home_id: UUID, configuration_id: UUID
    ) -> bool:
        row = await self.get_manual_configuration(home_id, configuration_id)
        if row is None:
            return False
        del self.manual[str(configuration_id)]
        return True


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
def gateway():
    gw = OptimizationGateway()
    home_id = "e4e4e4e4-e4e4-44e4-84e4-e4e4e4e4e4e4"
    gw.homes[home_id] = {"id": home_id, "name": "Casa", "primary_user_id": str(PRIMARY.id)}
    gw.home_members.add((home_id, str(MEMBER.id)))
    gw.home_id = home_id
    app.dependency_overrides[get_repository] = lambda: gw
    yield gw
    app.dependency_overrides.clear()


def act_as(user: UserProfile) -> None:
    app.dependency_overrides[get_current_user] = lambda: user


def url(gw: OptimizationGateway, path: str) -> str:
    return f"/api/v1/homes/{gw.home_id}{path}"


def save(gw: OptimizationGateway, layout: dict | None = None, version: int = 0):
    act_as(PRIMARY)
    return client.put(
        url(gw, "/layout"),
        json={"version": version, "layout": layout or small_layout()},
    )


def run(gw: OptimizationGateway, key: str | None = None):
    act_as(PRIMARY)
    return client.post(
        url(gw, "/optimization-runs"),
        json=RUN,
        headers={"Idempotency-Key": key or str(uuid4())},
    )


def test_layout_starts_from_template_without_costs(gateway: OptimizationGateway) -> None:
    act_as(MEMBER)
    response = client.get(url(gateway, "/layout"))

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "template"
    assert body["version"] == 0
    assert body["layout"]["budget"] is None


def test_layout_save_uses_optimistic_versioning(gateway: OptimizationGateway) -> None:
    first = save(gateway)
    second = save(gateway, version=1)
    stale = save(gateway, version=1)
    duplicate_first = save(gateway, version=0)

    assert first.status_code == 200 and first.json()["version"] == 1
    assert second.json()["version"] == 2
    assert stale.status_code == 409
    assert stale.json()["code"] == "LAYOUT_VERSION_CONFLICT"
    assert duplicate_first.status_code == 409


def test_layout_validation_errors_use_problem_details(gateway: OptimizationGateway) -> None:
    layout = small_layout()
    layout["critical_points"][0]["room_id"] = "inexistente"

    response = save(gateway, layout)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_permissions_follow_home_roles(gateway: OptimizationGateway) -> None:
    save(gateway)
    act_as(MEMBER)
    member_read = client.get(url(gateway, "/layout"))
    member_write = client.put(
        url(gateway, "/layout"), json={"version": 1, "layout": small_layout()}
    )
    member_run = client.post(
        url(gateway, "/optimization-runs"), json=RUN, headers={"Idempotency-Key": str(uuid4())}
    )
    act_as(OUTSIDER)
    outsider_read = client.get(url(gateway, "/layout"))
    act_as(MEMBER)
    missing_home = client.get(f"/api/v1/homes/{uuid4()}/layout")

    assert member_read.status_code == 200
    assert member_write.status_code == 403
    assert member_run.status_code == 403
    assert outsider_read.status_code == 403
    assert missing_home.status_code == 404


def test_run_requires_saved_and_complete_layout(gateway: OptimizationGateway) -> None:
    unsaved = run(gateway)
    incomplete = small_layout(budget=None)
    save(gateway, incomplete)
    not_ready = run(gateway)

    assert unsaved.status_code == 409
    assert unsaved.json()["code"] == "LAYOUT_REQUIRED"
    assert not_ready.status_code == 409
    assert not_ready.json()["code"] == "LAYOUT_INCOMPLETE"
    assert "budget" in not_ready.json()["detail"]


def test_run_persists_feasible_pareto_solutions(gateway: OptimizationGateway) -> None:
    save(gateway)
    response = run(gateway)

    assert response.status_code == 201
    body = response.json()
    assert body["algorithm"] == "NSGA-II"
    assert body["library"].startswith("pymoo ")
    assert body["seed"] == 7
    assert body["status"] == "completed"
    assert body["solution_count"] == len(body["solutions"]) > 0
    stock = {t["id"]: t["stock"] for t in body["layout"]["sensor_types"]}
    for solution in body["solutions"]:
        assert solution["metrics"]["cost"] <= body["layout"]["budget"]
        for type_id, count in solution["metrics"]["sensors_by_type"].items():
            assert count <= stock[type_id]
        candidates = [s["candidate_id"] for s in solution["sensors"]]
        assert len(candidates) == len(set(candidates))
    assert len(gateway.runs) == 1

    act_as(MEMBER)
    listed = client.get(url(gateway, "/optimization-runs"))
    detail = client.get(url(gateway, f"/optimization-runs/{body['id']}"))
    assert [item["id"] for item in listed.json()] == [body["id"]]
    assert detail.json()["solutions"] == body["solutions"]


def test_run_is_idempotent(gateway: OptimizationGateway) -> None:
    save(gateway)
    key = str(uuid4())
    first = run(gateway, key)
    replay = run(gateway, key)

    assert replay.status_code == 201
    assert replay.headers["idempotency-replayed"] == "true"
    assert replay.json()["id"] == first.json()["id"]
    assert len(gateway.runs) == 1


def test_solution_detail_recomputes_point_coverage(gateway: OptimizationGateway) -> None:
    save(gateway)
    body = run(gateway).json()
    best_coverage = max(body["solutions"], key=lambda s: s["metrics"]["coverage"])

    act_as(MEMBER)
    response = client.get(
        url(gateway, f"/optimization-runs/{body['id']}/solutions/{best_coverage['id']}")
    )
    other_run = client.get(
        url(gateway, f"/optimization-runs/{uuid4()}/solutions/{best_coverage['id']}")
    )

    assert response.status_code == 200
    points = response.json()["points"]
    covered = sum(point["covered"] for point in points) / len(points)
    assert covered == pytest.approx(best_coverage["metrics"]["coverage"])
    assert other_run.status_code == 404
    assert other_run.json()["code"] == "OPTIMIZATION_RUN_NOT_FOUND"


def test_runs_are_isolated_between_homes(gateway: OptimizationGateway) -> None:
    save(gateway)
    run_id = run(gateway).json()["id"]
    other_home = "f5f5f5f5-f5f5-45f5-85f5-f5f5f5f5f5f5"
    gateway.homes[other_home] = {
        "id": other_home, "name": "Outra", "primary_user_id": str(PRIMARY.id)
    }

    act_as(PRIMARY)
    response = client.get(f"/api/v1/homes/{other_home}/optimization-runs/{run_id}")

    assert response.status_code == 404


def test_evaluate_manual_configuration(gateway: OptimizationGateway) -> None:
    save(gateway, small_layout(budget=18))
    act_as(MEMBER)
    response = client.post(
        url(gateway, "/configurations/evaluate"),
        json={"sensors": [
            {"candidate_id": "c1", "sensor_type_id": "pir"},
            {"candidate_id": "c2", "sensor_type_id": "contact"},
        ]},
    )
    invalid = client.post(
        url(gateway, "/configurations/evaluate"),
        json={"sensors": [{"candidate_id": "c2", "sensor_type_id": "pir"}]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["metrics"]["cost"] == 19
    assert body["metrics"]["coverage"] == pytest.approx(2 / 3)
    assert body["feasible"] is False
    assert [v["code"] for v in body["violations"]] == ["BUDGET_EXCEEDED"]
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "INVALID_SENSOR_PLACEMENT"


def test_manual_configuration_lifecycle(gateway: OptimizationGateway) -> None:
    save(gateway)
    act_as(PRIMARY)
    created = client.post(
        url(gateway, "/manual-configurations"),
        json={"name": "  Só a sala ", "sensors": [{"candidate_id": "c1", "sensor_type_id": "pir"}]},
        headers={"Idempotency-Key": str(uuid4())},
    )
    config_id = created.json()["id"]
    listed = client.get(url(gateway, "/manual-configurations"))
    deleted = client.delete(url(gateway, f"/manual-configurations/{config_id}"))
    deleted_again = client.delete(url(gateway, f"/manual-configurations/{config_id}"))

    assert created.status_code == 201
    assert created.json()["name"] == "Só a sala"
    assert created.json()["evaluation"]["metrics"]["cost"] == 15
    assert [item["id"] for item in listed.json()] == [config_id]
    assert deleted.status_code == 204
    assert deleted_again.status_code == 404


def test_manual_configuration_reports_when_layout_changes(gateway: OptimizationGateway) -> None:
    save(gateway)
    act_as(PRIMARY)
    client.post(
        url(gateway, "/manual-configurations"),
        json={"name": "Contato", "sensors": [{"candidate_id": "c2", "sensor_type_id": "contact"}]},
        headers={"Idempotency-Key": str(uuid4())},
    )
    changed = small_layout()
    changed["candidate_points"] = changed["candidate_points"][:1]
    save(gateway, changed, version=1)

    listed = client.get(url(gateway, "/manual-configurations")).json()

    assert listed[0]["evaluation"] is None
    assert "c2" in listed[0]["evaluation_error"]


def test_compare_manual_against_pareto_front(gateway: OptimizationGateway) -> None:
    save(gateway)
    body = run(gateway).json()
    act_as(MEMBER)
    wasteful = {"sensors": [{"candidate_id": "c1", "sensor_type_id": "contact"}]}

    response = client.post(url(gateway, f"/optimization-runs/{body['id']}/compare"), json=wasteful)

    assert response.status_code == 200
    comparison = response.json()
    # Um contato em c1 custa 4 e não cobre nenhum ponto: a solução vazia o domina.
    assert comparison["manual"]["metrics"]["coverage"] == 0
    assert comparison["manual_is_dominated"] is True
    assert len(comparison["entries"]) == len(body["solutions"])
    empty = next(e for e in comparison["entries"] if e["metrics"]["sensor_count"] == 0)
    assert empty["solution_dominates_manual"] is True
    assert empty["delta_cost"] == -4
    assert not any(e["manual_dominates_solution"] for e in comparison["entries"])


def test_compare_with_saved_manual_configuration(gateway: OptimizationGateway) -> None:
    save(gateway)
    body = run(gateway).json()
    act_as(PRIMARY)
    config = client.post(
        url(gateway, "/manual-configurations"),
        json={"name": "Completa", "sensors": [
            {"candidate_id": "c1", "sensor_type_id": "pir"},
            {"candidate_id": "c2", "sensor_type_id": "contact"},
        ]},
        headers={"Idempotency-Key": str(uuid4())},
    ).json()

    response = client.post(
        url(gateway, f"/optimization-runs/{body['id']}/compare"),
        json={"manual_configuration_id": config["id"]},
    )
    both = client.post(
        url(gateway, f"/optimization-runs/{body['id']}/compare"),
        json={"manual_configuration_id": config["id"], "sensors": []},
    )

    assert response.status_code == 200
    # Esta configuração é ótima de Pareto na instância pequena: nenhuma solução a domina.
    assert response.json()["manual_is_dominated"] is False
    assert both.status_code == 422


def test_optimization_routes_are_documented(gateway: OptimizationGateway) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    base = "/api/v1/homes/{home_id}"

    assert {"get", "put"} <= paths[f"{base}/layout"].keys()
    assert "post" in paths[f"{base}/optimization-runs"]
    assert "409" in paths[f"{base}/optimization-runs"]["post"]["responses"]
    assert "post" in paths[f"{base}/optimization-runs/{{run_id}}/compare"]
    assert "delete" in paths[f"{base}/manual-configurations/{{configuration_id}}"]
    assert {"bearerAuth": []} in paths[f"{base}/layout"]["get"]["security"]
