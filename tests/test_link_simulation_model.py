from modules.service.link_simulation_model import simulate

TRIALS = 400
SEED = 11


def run(scenario: str, defenses: tuple[str, ...] = (), intensity: float = 1.0):
    return simulate(scenario, intensity, defenses, TRIALS, SEED)


def test_same_seed_reproduces_the_result() -> None:
    assert run("jamming", ("heartbeat",)) == run("jamming", ("heartbeat",))


def test_healthy_network_delivers_the_alert() -> None:
    outcome, _ = run("baseline")

    assert outcome.metrics.verdict == "delivered"
    assert outcome.metrics.delivery_rate >= 0.99
    assert outcome.metrics.latency_p50_ms < 200
    assert [hop.status for hop in outcome.hops] == ["ok", "ok", "ok", "ok"]


def test_zero_intensity_keeps_the_healthy_network() -> None:
    outcome, _ = run("jamming", intensity=0.0)

    assert outcome.metrics.verdict == "delivered"
    assert outcome.hops[0].status == "ok"


def test_full_jamming_without_defense_is_silent() -> None:
    outcome, _ = run("jamming")

    assert outcome.metrics.delivery_rate == 0
    assert outcome.metrics.aware_rate == 0
    assert outcome.metrics.latency_p50_ms is None
    assert outcome.metrics.verdict == "silent"
    assert outcome.hops[0].status == "down"
    assert outcome.timeline[-1].kind == "failed"


def test_heartbeat_warns_the_resident_about_jamming() -> None:
    outcome, without = run("jamming", ("heartbeat",))

    assert outcome.metrics.delivery_rate == 0
    assert outcome.metrics.aware_rate >= 0.99
    assert outcome.metrics.verdict == "aware"
    assert outcome.metrics.aware_p50_ms > 30_000
    assert without.verdict == "silent"
    assert outcome.timeline[-1].kind == "notice"


def test_local_siren_only_covers_the_house() -> None:
    outcome, _ = run("jamming", ("local_siren",))

    assert outcome.metrics.local_alarm is True
    assert outcome.metrics.aware_rate == 0
    assert outcome.metrics.verdict == "local_only"


def test_failover_recovers_a_fibre_outage() -> None:
    outcome, without = run("wan_failure", ("sdwan_failover",))

    assert without.verdict == "silent"
    assert outcome.metrics.verdict == "delivered"
    assert outcome.metrics.latency_p50_ms >= 3_000
    assert "backup_wan" in [hop.id for hop in outcome.hops]
    assert "failover" in [event.kind for event in outcome.timeline]


def test_fake_base_station_exposes_sms_and_blocks_delivery() -> None:
    outcome, _ = run("fake_base_station")

    assert outcome.metrics.exposure_rate == 1
    assert outcome.metrics.delivery_rate < 0.5
    assert outcome.hops[-1].status == "rogue"


def test_encrypted_push_protects_content_but_not_delivery() -> None:
    outcome, _ = run("fake_base_station", ("encrypted_push",))

    assert outcome.metrics.exposure_rate == 0
    assert outcome.metrics.delivery_rate < 0.5


def test_blocking_2g_restores_delivery_and_privacy() -> None:
    outcome, without = run("fake_base_station", ("block_2g",))

    assert without.exposure_rate == 1
    assert outcome.metrics.exposure_rate == 0
    assert outcome.metrics.verdict == "delivered"
    assert "rogue_cell" not in [hop.id for hop in outcome.hops]


def test_cells_compare_real_and_fake_antennas() -> None:
    outcome, _ = run("fake_base_station", intensity=0.2)
    real, fake = outcome.cells

    assert (real.id, real.generation, real.identity_protected) == ("real", "5G", True)
    assert real.delivery_rate >= 0.99 and real.exposure_rate == 0
    assert (fake.id, fake.generation, fake.blocked) == ("fake", "2G", False)
    assert fake.network_authenticated is False and fake.identity_protected is False
    assert fake.delivery_rate < 0.5 and fake.exposure_rate == 1


def test_encrypted_push_only_protects_content_on_fake_antenna() -> None:
    outcome, _ = run("fake_base_station", ("encrypted_push",))
    fake = outcome.cells[1]

    assert fake.content_protected is True
    assert fake.identity_protected is False
    assert fake.exposure_rate == 0


def test_blocking_2g_makes_the_phone_refuse_the_fake_antenna() -> None:
    outcome, _ = run("fake_base_station", ("block_2g",))
    real, fake = outcome.cells

    assert fake.blocked is True
    assert fake.generation == "2G"
    assert fake.delivery_rate == real.delivery_rate


def test_only_fake_base_station_reports_cells() -> None:
    assert run("jamming")[0].cells == []
    assert run("jamming")[0].generations == []


def fake_on(generation: str, defenses: tuple[str, ...] = ()):
    return simulate("fake_base_station", 1.0, defenses, TRIALS, SEED, generation)[0]


def test_3g_and_4g_expose_identity_but_not_the_code() -> None:
    for generation in ("3G", "4G"):
        outcome = fake_on(generation)
        fake = outcome.cells[1]

        assert fake.generation == generation
        assert fake.network_authenticated is True
        assert fake.identity_protected is False
        assert fake.content_protected is True
        assert outcome.metrics.exposure_rate == 0
        assert outcome.metrics.verdict == "delivered"
        assert "identity_exposed" in [event.kind for event in outcome.timeline]
        assert "auth_failed" in [event.kind for event in outcome.timeline]


def test_5g_conceals_the_identity_too() -> None:
    outcome = fake_on("5G")

    assert outcome.cells[1].identity_protected is True
    assert outcome.metrics.verdict == "delivered"
    assert "identity_exposed" not in [event.kind for event in outcome.timeline]


def test_table_compares_all_generations() -> None:
    rows = {cell.generation: cell for cell in fake_on("4G").generations}

    assert list(rows) == ["2G", "3G", "4G", "5G"]
    assert rows["2G"].exposure_rate == 1
    assert all(rows[g].exposure_rate == 0 for g in ("3G", "4G", "5G"))
    assert [rows[g].identity_protected for g in rows] == [False, False, False, True]


def test_block_2g_only_affects_the_2g_antenna() -> None:
    rows = {cell.generation: cell for cell in fake_on("4G", ("block_2g",)).generations}

    assert rows["2G"].blocked is True
    assert rows["4G"].blocked is False
    assert rows["4G"].identity_protected is False


def test_fake_antenna_delays_the_delivery_when_rejected() -> None:
    healthy = fake_on("2G", ("block_2g",)).metrics.latency_p50_ms
    assert fake_on("4G").metrics.latency_p50_ms > healthy + 1_000


def test_irrelevant_defense_changes_nothing() -> None:
    outcome, without = run("fake_base_station", ("sdwan_failover",))

    assert outcome.metrics.delivery_rate == without.delivery_rate
    assert outcome.metrics.exposure_rate == without.exposure_rate
