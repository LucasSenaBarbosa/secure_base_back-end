import copy
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from test_api import FakeGateway, account, app, client

from modules.auth.dependencies import get_current_user, get_repository
from modules.schemas.auth_schemas import Role, UserProfile

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
BODY = {"scenario": "jamming", "defenses": ["heartbeat"], "trials": 100, "seed": 5}


class LinkGateway(FakeGateway):
    def __init__(self) -> None:
        super().__init__(accounts=[account()])
        self.simulations: dict[str, dict[str, object]] = {}

    async def create_link_simulation(self, simulation: dict) -> dict[str, object]:
        row = {**simulation, "created_at": datetime.now(timezone.utc).isoformat()}
        row.pop("created_by")
        self.simulations[row["id"]] = row
        return copy.deepcopy(row)

    async def list_link_simulations(
        self, home_id: UUID, *, limit: int, offset: int
    ) -> list[dict[str, object]]:
        rows = [
            {key: value for key, value in row.items() if key != "result"}
            for row in self.simulations.values()
            if row["home_id"] == str(home_id)
        ]
        return rows[offset : offset + limit]

    async def get_link_simulation(
        self, home_id: UUID, simulation_id: UUID
    ) -> dict[str, object] | None:
        row = self.simulations.get(str(simulation_id))
        return copy.deepcopy(row) if row and row["home_id"] == str(home_id) else None


@pytest.fixture
def gateway():
    gw = LinkGateway()
    home_id = "e4e4e4e4-e4e4-44e4-84e4-e4e4e4e4e4e4"
    gw.homes[home_id] = {"id": home_id, "name": "Casa", "primary_user_id": str(PRIMARY.id)}
    gw.home_members.add((home_id, str(MEMBER.id)))
    gw.home_id = home_id
    app.dependency_overrides[get_repository] = lambda: gw
    yield gw
    app.dependency_overrides.clear()


def act_as(user: UserProfile) -> None:
    app.dependency_overrides[get_current_user] = lambda: user


def url(gw: LinkGateway, path: str = "") -> str:
    return f"/api/v1/homes/{gw.home_id}/link-simulations{path}"


def post(gw: LinkGateway, body: dict | None = None, key: str | None = None):
    return client.post(
        url(gw),
        json=body or BODY,
        headers={"Idempotency-Key": key or str(uuid4())},
    )


def test_catalog_links_scenarios_to_lessons(gateway: LinkGateway) -> None:
    act_as(MEMBER)
    body = client.get(url(gateway, "/catalog")).json()

    assert {item["id"] for item in body["scenarios"]} >= {"jamming", "fake_base_station"}
    assert all(item["lessons"] for item in body["scenarios"])
    defenses = {item["id"] for item in body["defenses"]}
    for scenario in body["scenarios"]:
        assert set(scenario["relevant_defenses"]) <= defenses


def test_member_runs_and_reads_a_simulation(gateway: LinkGateway) -> None:
    act_as(MEMBER)
    created = post(gateway)

    assert created.status_code == 201
    body = created.json()
    assert body["metrics"]["verdict"] == "aware"
    assert body["without_defenses"]["verdict"] == "silent"
    assert body["timeline"]

    listed = client.get(url(gateway)).json()
    detail = client.get(url(gateway, f"/{body['id']}"))
    assert [item["id"] for item in listed] == [body["id"]]
    assert "metrics" not in listed[0]
    assert detail.json() == body


def test_fake_generation_is_returned_and_validated(gateway: LinkGateway) -> None:
    act_as(MEMBER)
    body = {"scenario": "fake_base_station", "fake_generation": "4G", "trials": 100, "seed": 5}
    created = post(gateway, body).json()
    invalid = post(gateway, {**body, "fake_generation": "6G"})

    assert created["fake_generation"] == "4G"
    assert created["cells"][1]["generation"] == "4G"
    assert [row["generation"] for row in created["generations"]] == ["2G", "3G", "4G", "5G"]
    assert invalid.status_code == 422


def test_idempotency_key_does_not_duplicate_the_run(gateway: LinkGateway) -> None:
    act_as(MEMBER)
    key = str(uuid4())
    first = post(gateway, key=key)
    second = post(gateway, key=key)

    assert first.json()["id"] == second.json()["id"]
    assert len(gateway.simulations) == 1


def test_permissions_follow_home_membership(gateway: LinkGateway) -> None:
    act_as(OUTSIDER)
    denied_catalog = client.get(url(gateway, "/catalog"))
    denied_run = post(gateway)
    act_as(MEMBER)
    missing_home = client.get(f"/api/v1/homes/{uuid4()}/link-simulations/catalog")

    assert denied_catalog.status_code == 403
    assert denied_run.status_code == 403
    assert missing_home.status_code == 404
    assert gateway.simulations == {}


def test_simulation_from_another_home_is_not_found(gateway: LinkGateway) -> None:
    act_as(MEMBER)
    created = post(gateway).json()
    gateway.simulations[created["id"]]["home_id"] = str(uuid4())

    response = client.get(url(gateway, f"/{created['id']}"))

    assert response.status_code == 404
    assert response.json()["code"] == "LINK_SIMULATION_NOT_FOUND"


@pytest.mark.parametrize(
    "change",
    [
        {"scenario": "ataque-real"},
        {"intensity": 1.5},
        {"defenses": ["heartbeat", "heartbeat"]},
        {"trials": 10},
        {"extra": True},
    ],
)
def test_invalid_input_is_rejected(gateway: LinkGateway, change: dict) -> None:
    act_as(MEMBER)
    response = post(gateway, {**BODY, **change})

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_routes_are_documented(gateway: LinkGateway) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    base = "/api/v1/homes/{home_id}/link-simulations"

    assert {"get", "post"} <= paths[base].keys()
    assert "get" in paths[f"{base}/catalog"]
    assert "get" in paths[f"{base}/{{simulation_id}}"]
