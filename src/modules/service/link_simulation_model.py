"""Modelo didático do caminho de um alerta entre a casa e o celular do morador.

Sem I/O e determinístico pela semente. Os valores são ilustrativos: servem para
comparar cenários e defesas, não para prever o desempenho de uma rede real.
"""

import random
import statistics
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace

MODEL_VERSION = "1.0"
MAX_ATTEMPTS = 4
ACK_TIMEOUTS_MS = (1_000, 2_000, 4_000, 8_000)
FAILOVER_MS = 3_000
HEARTBEAT_INTERVAL_MS = 10_000
HEARTBEAT_MISSES = 3
HEARTBEAT_WINDOW = 12
LOCAL_SIREN_MS = 50
RESELECT_MS = 2_000
ROGUE_CELL_LOSS = 0.9
DEGRADED_LOSS = 0.05
DOWN_LOSS = 0.95
DELIVERED_THRESHOLD = 0.95
PARTIAL_THRESHOLD = 0.5


@dataclass(frozen=True)
class Hop:
    id: str
    label: str
    latency_ms: float
    jitter_ms: float
    loss: float


WIFI = Hop("wifi", "Wi-Fi da casa", 5, 3, 0.005)
WAN = Hop("wan", "Fibra (WAN principal)", 25, 5, 0.001)
BACKUP_WAN = Hop("backup_wan", "4G/5G de reserva", 60, 15, 0.01)
API = Hop("api", "API SecureBase", 15, 2, 0.0)
MOBILE = Hop("mobile", "Rede móvel 5G", 30, 8, 0.005)


@dataclass(frozen=True)
class Generation:
    id: str
    network_authenticated: bool
    identity_concealed: bool
    latency_ms: float
    jitter_ms: float

    @property
    def rogue_hop(self) -> Hop:
        label = f"Antena falsa ({self.id})"
        return Hop("rogue_cell", label, self.latency_ms, self.jitter_ms, ROGUE_CELL_LOSS)


GENERATIONS = {
    generation.id: generation
    for generation in (
        Generation("2G", False, False, 300, 60),
        Generation("3G", True, False, 120, 25),
        Generation("4G", True, False, 50, 10),
        Generation("5G", True, True, 30, 8),
    )
}


@dataclass(frozen=True)
class Event:
    t_ms: int
    kind: str
    hop: str | None
    message: str


@dataclass(frozen=True)
class Conditions:
    wifi: Hop
    wan: Hop
    rogue_probability: float
    defenses: frozenset[str]
    generation: Generation = GENERATIONS["2G"]

    def has(self, defense: str) -> bool:
        return defense in self.defenses


@dataclass(frozen=True)
class Metrics:
    delivery_rate: float
    aware_rate: float
    exposure_rate: float
    packet_loss: float
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    jitter_ms: float | None
    aware_p50_ms: float | None
    local_alarm: bool
    verdict: str


@dataclass(frozen=True)
class HopStatus:
    id: str
    label: str
    latency_ms: float
    loss: float
    status: str


@dataclass(frozen=True)
class CellResult:
    id: str
    label: str
    generation: str
    blocked: bool
    network_authenticated: bool
    identity_protected: bool
    content_protected: bool
    delivery_rate: float
    exposure_rate: float
    latency_p50_ms: float | None


@dataclass(frozen=True)
class Outcome:
    metrics: Metrics
    hops: list[HopStatus]
    timeline: list[Event]
    cells: list[CellResult] = field(default_factory=list)
    generations: list[CellResult] = field(default_factory=list)


@dataclass
class _Trial:
    rng: random.Random
    conditions: Conditions
    t: float = 0.0
    sent: int = 0
    lost: int = 0
    failed_over: bool = False
    exposed: bool = False
    events: list[Event] = field(default_factory=list)

    def note(self, kind: str, message: str, hop: str | None = None) -> None:
        self.events.append(Event(round(self.t), kind, hop, message))

    def active_wan(self) -> Hop:
        return BACKUP_WAN if self.failed_over else self.conditions.wan

    def upstream(self) -> list[Hop]:
        return [self.conditions.wifi, self.active_wan(), API]

    def lost_on(self, hop: Hop) -> bool:
        return self.rng.random() < hop.loss

    def travel(self, hop: Hop) -> None:
        self.t += max(1.0, self.rng.gauss(hop.latency_ms, hop.jitter_ms))

    def can_fail_over(self, hop: Hop) -> bool:
        return (
            hop.id == "wan"
            and self.conditions.has("sdwan_failover")
            and not self.failed_over
        )

    def send(self, paths: Callable[[], list[Hop]], *, counted: bool = True) -> bool:
        """Envia por um segmento, com retransmissão; devolve se chegou ao fim."""
        attempt = 0
        while attempt < MAX_ATTEMPTS:
            failed_hop = self._attempt(paths(), counted=counted)
            if failed_hop is None:
                return True
            if self.can_fail_over(failed_hop):
                self.t += FAILOVER_MS
                self.failed_over = True
                self.note("failover", "SD-WAN trocou a rota para o 4G/5G.", "backup_wan")
                continue
            self.t += ACK_TIMEOUTS_MS[attempt]
            attempt += 1
            if attempt < MAX_ATTEMPTS:
                self.note("retry", f"Sem confirmação; tentativa {attempt + 1} de {MAX_ATTEMPTS}.")
        return False

    def _attempt(self, hops: list[Hop], *, counted: bool) -> Hop | None:
        if counted:
            self.sent += 1
        for hop in hops:
            if self.lost_on(hop):
                if counted:
                    self.lost += 1
                self.note("loss", f"Pacote perdido em: {hop.label}.", hop.id)
                return hop
            self.travel(hop)
            self.note("hop", f"Passou por: {hop.label}.", hop.id)
        return None

    def heartbeat_detects_outage(self) -> bool:
        misses = 0
        for _ in range(HEARTBEAT_WINDOW):
            self.t += HEARTBEAT_INTERVAL_MS
            if not any(self.lost_on(hop) for hop in self.upstream()):
                misses = 0
                continue
            misses += 1
            detail = f"Heartbeat ausente ({misses}/{HEARTBEAT_MISSES})."
            self.note("heartbeat_missed", detail, "api")
            if misses == HEARTBEAT_MISSES:
                return True
        return False


@dataclass(frozen=True)
class _TrialResult:
    label: str
    delivered_ms: float | None
    aware_ms: float | None
    exposed: bool
    sent: int
    lost: int
    events: list[Event]


@dataclass(frozen=True)
class _Messages:
    start: str
    exposed: str
    delivered: str
    failed: str


_INVASION = _Messages(
    start="Sensor de presença detectou movimento; ESP32 envia o alerta.",
    exposed="Antena falsa leu o alerta em texto claro.",
    delivered="Alerta de invasão chegou ao celular do morador.",
    failed="O morador não ficou sabendo da invasão.",
)
_ACCESS_CODE = _Messages(
    start="Porta pediu confirmação; o código de acesso sai por SMS.",
    exposed="Antena falsa leu o código de acesso no SMS em texto claro.",
    delivered="Código de acesso chegou ao celular do morador.",
    failed="O morador não recebeu o código de acesso.",
)


def conditions_for(
    scenario: str,
    intensity: float,
    defenses: Iterable[str],
    fake_generation: str = "2G",
) -> Conditions:
    active = frozenset(defenses)
    generation = GENERATIONS[fake_generation]
    blocked = generation.id == "2G" and "block_2g" in active
    wifi = WIFI
    wan = WAN
    rogue_probability = 0.0
    if scenario == "jamming":
        wifi = Hop(WIFI.id, WIFI.label, WIFI.latency_ms, WIFI.jitter_ms, max(WIFI.loss, intensity))
    elif scenario == "wan_failure":
        wan = Hop(WAN.id, WAN.label, WAN.latency_ms, WAN.jitter_ms, max(WAN.loss, intensity))
    elif scenario == "fake_base_station" and not blocked:
        rogue_probability = intensity
    return Conditions(wifi, wan, rogue_probability, active, generation)


def _run_trial(rng: random.Random, scenario: str, conditions: Conditions) -> _TrialResult:
    trial = _Trial(rng, conditions)
    messages = _ACCESS_CODE if scenario == "fake_base_station" else _INVASION
    trial.note("start", messages.start)
    if conditions.has("local_siren"):
        trial.events.append(
            Event(LOCAL_SIREN_MS, "local_alarm", None, "Sirene local tocou, sem depender da rede.")
        )

    generation = conditions.generation
    camped = rng.random() < conditions.rogue_probability
    if camped and generation.network_authenticated:
        if not generation.identity_concealed:
            trial.note("identity_exposed", "Antena falsa capturou a identidade do aparelho.")
        trial.note("auth_failed", f"Antena falsa {generation.id} não provou ser da operadora.")
        trial.t += RESELECT_MS
        camped = False
    elif camped:
        trial.note("downgrade", "Celular foi rebaixado para 2G na antena falsa.", "rogue_cell")
    elif (
        scenario == "fake_base_station"
        and generation.id == "2G"
        and conditions.has("block_2g")
    ):
        trial.note("downgrade_blocked", "Celular recusou o rebaixamento para 2G.", "mobile")

    last_hop = generation.rogue_hop if camped else MOBILE

    def downstream() -> list[Hop]:
        return [last_hop]

    delivered_ms: float | None = None
    aware_ms: float | None = None
    if trial.send(trial.upstream):
        if camped and not conditions.has("encrypted_push"):
            trial.exposed = True
            trial.note("exposed", messages.exposed, "rogue_cell")
        if trial.send(downstream):
            delivered_ms = aware_ms = trial.t
            trial.note("delivered", messages.delivered, last_hop.id)
    elif conditions.has("heartbeat") and trial.heartbeat_detects_outage():
        if trial.send(downstream, counted=False):
            aware_ms = trial.t
            trial.note("notice", "Morador avisado: a casa parou de responder.", last_hop.id)

    label = "delivered" if delivered_ms is not None else "aware" if aware_ms is not None else "lost"
    if label == "lost":
        trial.note("failed", messages.failed)
    trial.events.sort(key=lambda event: event.t_ms)
    return _TrialResult(
        label, delivered_ms, aware_ms, trial.exposed, trial.sent, trial.lost, trial.events
    )


def _percentile(sorted_values: list[float], fraction: float) -> float:
    rank = max(1, round(fraction * len(sorted_values)))
    return sorted_values[rank - 1]


def _jitter(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    return statistics.fmean(abs(b - a) for a, b in zip(values, values[1:], strict=False))


def _verdict(delivery: float, aware: float, local_alarm: bool) -> str:
    if delivery >= DELIVERED_THRESHOLD:
        return "delivered"
    if aware >= DELIVERED_THRESHOLD:
        return "aware"
    if aware >= PARTIAL_THRESHOLD:
        return "degraded"
    return "local_only" if local_alarm else "silent"


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


def _metrics(results: list[_TrialResult], conditions: Conditions) -> Metrics:
    total = len(results)
    delivered = [r.delivered_ms for r in results if r.delivered_ms is not None]
    aware = sorted(r.aware_ms for r in results if r.aware_ms is not None)
    ordered = sorted(delivered)
    sent = sum(r.sent for r in results)
    delivery_rate = len(delivered) / total
    aware_rate = len(aware) / total
    local_alarm = conditions.has("local_siren")
    return Metrics(
        delivery_rate=round(delivery_rate, 4),
        aware_rate=round(aware_rate, 4),
        exposure_rate=round(sum(r.exposed for r in results) / total, 4),
        packet_loss=round(sum(r.lost for r in results) / sent, 4) if sent else 0.0,
        latency_p50_ms=_round(_percentile(ordered, 0.5)) if ordered else None,
        latency_p95_ms=_round(_percentile(ordered, 0.95)) if ordered else None,
        jitter_ms=_round(_jitter(delivered)),
        aware_p50_ms=_round(_percentile(aware, 0.5)) if aware else None,
        local_alarm=local_alarm,
        verdict=_verdict(delivery_rate, aware_rate, local_alarm),
    )


def _status(hop: Hop, *, rogue: bool = False) -> HopStatus:
    if rogue:
        status = "rogue"
    elif hop.loss >= DOWN_LOSS:
        status = "down"
    elif hop.loss >= DEGRADED_LOSS:
        status = "degraded"
    else:
        status = "ok"
    return HopStatus(hop.id, hop.label, hop.latency_ms, round(hop.loss, 4), status)


def _hops(conditions: Conditions) -> list[HopStatus]:
    hops = [_status(conditions.wifi), _status(conditions.wan)]
    if conditions.has("sdwan_failover"):
        hops.append(_status(BACKUP_WAN))
    hops += [_status(API), _status(MOBILE)]
    if conditions.rogue_probability > 0:
        hops.append(_status(conditions.generation.rogue_hop, rogue=True))
    return hops


def _simulate(
    scenario: str,
    intensity: float,
    defenses: Iterable[str],
    trials: int,
    seed: int,
    fake_generation: str,
) -> Outcome:
    rng = random.Random(seed)
    conditions = conditions_for(scenario, intensity, defenses, fake_generation)
    results = [_run_trial(rng, scenario, conditions) for _ in range(trials)]
    most_common = Counter(r.label for r in results).most_common(1)[0][0]
    example = next(r for r in results if r.label == most_common)
    return Outcome(_metrics(results, conditions), _hops(conditions), example.events)


def _cell_metrics(
    camped: bool,
    defenses: list[str],
    trials: int,
    seed: int,
    generation: Generation,
) -> Metrics:
    rng = random.Random(seed)
    conditions = Conditions(WIFI, WAN, 1.0 if camped else 0.0, frozenset(defenses), generation)
    results = [_run_trial(rng, "fake_base_station", conditions) for _ in range(trials)]
    return _metrics(results, conditions)


def _real_cell(defenses: list[str], trials: int, seed: int) -> tuple[CellResult, Metrics]:
    metrics = _cell_metrics(False, defenses, trials, seed, GENERATIONS["5G"])
    cell = CellResult(
        "real", "Antena verdadeira", "5G", False, True, True, True,
        metrics.delivery_rate, metrics.exposure_rate, metrics.latency_p50_ms,
    )
    return cell, metrics


def _fake_cell(
    generation: Generation,
    real: Metrics,
    defenses: list[str],
    trials: int,
    seed: int,
) -> CellResult:
    """Resultado de o celular encontrar uma antena falsa desta geração."""
    blocked = generation.id == "2G" and "block_2g" in defenses
    metrics = real if blocked else _cell_metrics(True, defenses, trials, seed, generation)
    return CellResult(
        "fake", f"Antena falsa ({generation.id})", generation.id, blocked,
        blocked or generation.network_authenticated,
        blocked or generation.identity_concealed,
        blocked or generation.network_authenticated or "encrypted_push" in defenses,
        metrics.delivery_rate, metrics.exposure_rate, metrics.latency_p50_ms,
    )


def simulate(
    scenario: str,
    intensity: float,
    defenses: Iterable[str],
    trials: int,
    seed: int,
    fake_generation: str = "2G",
) -> tuple[Outcome, Metrics]:
    """Devolve o resultado com as defesas e as métricas do mesmo cenário sem elas."""
    chosen = list(defenses)
    outcome = _simulate(scenario, intensity, chosen, trials, seed, fake_generation)
    if scenario == "fake_base_station":
        real_cell, real = _real_cell(chosen, trials, seed)
        generations = [
            _fake_cell(generation, real, chosen, trials, seed)
            for generation in GENERATIONS.values()
        ]
        fake_cell = next(cell for cell in generations if cell.generation == fake_generation)
        outcome = replace(outcome, cells=[real_cell, fake_cell], generations=generations)
    if not chosen:
        return outcome, outcome.metrics
    return outcome, _simulate(scenario, intensity, [], trials, seed, fake_generation).metrics
