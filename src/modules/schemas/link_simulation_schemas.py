from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

Scenario = Literal["baseline", "jamming", "wan_failure", "fake_base_station"]
Defense = Literal["heartbeat", "local_siren", "sdwan_failover", "block_2g", "encrypted_push"]
HopId = Literal["wifi", "wan", "backup_wan", "api", "mobile", "rogue_cell"]
HopStatus = Literal["ok", "degraded", "down", "rogue"]
Verdict = Literal["delivered", "aware", "degraded", "local_only", "silent"]
Generation = Literal["2G", "3G", "4G", "5G"]
EventKind = Literal[
    "start",
    "hop",
    "loss",
    "retry",
    "failover",
    "downgrade",
    "downgrade_blocked",
    "identity_exposed",
    "auth_failed",
    "heartbeat_missed",
    "notice",
    "exposed",
    "delivered",
    "failed",
    "local_alarm",
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScenarioInfo(_Strict):
    id: Scenario
    label: str
    description: str
    lessons: list[str]
    relevant_defenses: list[Defense]


class DefenseInfo(_Strict):
    id: Defense
    label: str
    description: str
    lessons: list[str]


class LinkCatalog(_Strict):
    model_version: str
    notice: str = Field(description="Aviso sobre o caráter didático dos valores do modelo.")
    scenarios: list[ScenarioInfo]
    defenses: list[DefenseInfo]


class LinkSimulationRequest(_Strict):
    scenario: Scenario
    intensity: float = Field(
        default=1.0,
        ge=0,
        le=1,
        description="Força do ataque ou da falha; 0 não altera o enlace.",
    )
    defenses: list[Defense] = Field(default_factory=list, max_length=5)
    fake_generation: Generation = Field(
        default="2G",
        description="Geração usada pela antena falsa; só tem efeito nesse cenário.",
    )
    trials: int = Field(default=500, ge=50, le=2000, description="Número de alertas simulados.")
    seed: int | None = Field(
        default=None,
        ge=0,
        lt=2**31,
        description="Semente; a mesma entrada com a mesma semente gera o mesmo resultado.",
    )

    @field_validator("defenses")
    @classmethod
    def validate_defenses(cls, value: list[Defense]) -> list[Defense]:
        if len(set(value)) != len(value):
            raise ValueError("Defesas não podem ser repetidas.")
        return sorted(value)


class HopReport(_Strict):
    id: HopId
    label: str
    latency_ms: float
    loss: float = Field(ge=0, le=1)
    status: HopStatus


class LinkMetrics(_Strict):
    delivery_rate: float = Field(ge=0, le=1, description="Fração de alertas que chegou.")
    aware_rate: float = Field(
        ge=0,
        le=1,
        description="Fração em que o morador recebeu o alerta ou o aviso de perda de contato.",
    )
    exposure_rate: float = Field(
        ge=0,
        le=1,
        description="Fração em que o conteúdo do alerta ficou legível para o atacante.",
    )
    packet_loss: float = Field(ge=0, le=1, description="Perda por tentativa de envio.")
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    jitter_ms: float | None
    aware_p50_ms: float | None
    local_alarm: bool
    verdict: Verdict


class TimelineEvent(_Strict):
    t_ms: int = Field(ge=0)
    kind: EventKind
    hop: HopId | None = None
    message: str


class CellResult(_Strict):
    id: Literal["real", "fake"]
    label: str
    generation: Generation
    blocked: bool = Field(description="O celular recusou esta antena.")
    network_authenticated: bool = Field(description="O celular exige que a rede prove quem é.")
    identity_protected: bool
    content_protected: bool
    delivery_rate: float = Field(ge=0, le=1)
    exposure_rate: float = Field(ge=0, le=1)
    latency_p50_ms: float | None


class LinkSimulationSummary(_Strict):
    id: UUID
    home_id: UUID
    created_at: datetime
    scenario: Scenario
    intensity: float
    defenses: list[Defense]
    trials: int
    seed: int
    model_version: str
    verdict: Verdict
    delivery_rate: float


class LinkSimulationDetail(LinkSimulationSummary):
    metrics: LinkMetrics
    without_defenses: LinkMetrics = Field(
        description="Mesmo cenário e mesma semente, sem nenhuma defesa ativa.",
    )
    hops: list[HopReport]
    timeline: list[TimelineEvent] = Field(
        description="Passo a passo do desfecho mais frequente entre as tentativas.",
    )
    cells: list[CellResult] = Field(
        default_factory=list,
        description="Resultado em cada antena; preenchido só no cenário de antena falsa.",
    )
    fake_generation: Generation = "2G"
    generations: list[CellResult] = Field(
        default_factory=list,
        description="Antena falsa em cada geração; preenchido só nesse cenário.",
    )
