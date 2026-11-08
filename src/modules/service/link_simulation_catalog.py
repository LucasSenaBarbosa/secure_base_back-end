"""Catálogo de cenários e defesas do laboratório de rede, ligado às aulas da disciplina."""

from modules.schemas.link_simulation_schemas import DefenseInfo, LinkCatalog, ScenarioInfo
from modules.service.link_simulation_model import MODEL_VERSION

_NOTICE = (
    "Simulação didática: nenhum sinal de rádio ou tráfego real é gerado, e latências e perdas "
    "são valores ilustrativos para comparar cenários."
)

_SCENARIOS = [
    ScenarioInfo(
        id="baseline",
        label="Rede saudável",
        description="Caminho normal do alerta, usado como referência.",
        lessons=["Aula 06"],
        relevant_defenses=[],
    ),
    ScenarioInfo(
        id="jamming",
        label="Interferência no Wi-Fi (jamming)",
        description="Ruído no canal impede o ESP32 de falar com o roteador.",
        lessons=["Aula 13"],
        relevant_defenses=["heartbeat", "local_siren"],
    ),
    ScenarioInfo(
        id="wan_failure",
        label="Queda da fibra",
        description="A WAN principal da casa fica indisponível.",
        lessons=["Aula 03", "Aula 04"],
        relevant_defenses=["sdwan_failover", "heartbeat", "local_siren"],
    ),
    ScenarioInfo(
        id="fake_base_station",
        label="Antena falsa",
        description="O celular é atraído para uma antena falsa, de 2G a 5G.",
        lessons=["Aula 06", "Aula 07", "Aula 12"],
        relevant_defenses=["block_2g", "encrypted_push", "local_siren"],
    ),
]

_DEFENSES = [
    DefenseInfo(
        id="heartbeat",
        label="Heartbeat",
        description="O morador é avisado quando a casa para de dar sinal de vida.",
        lessons=["Aula 05", "Aula 13"],
    ),
    DefenseInfo(
        id="local_siren",
        label="Sirene local",
        description="A casa alerta quem está nela sem depender da rede.",
        lessons=["Aula 05"],
    ),
    DefenseInfo(
        id="sdwan_failover",
        label="Failover SD-WAN",
        description="Troca para o 4G/5G de reserva quando a fibra falha.",
        lessons=["Aula 04"],
    ),
    DefenseInfo(
        id="block_2g",
        label="Bloquear 2G",
        description="O celular recusa o rebaixamento para 2G.",
        lessons=["Aula 07", "Aula 12"],
    ),
    DefenseInfo(
        id="encrypted_push",
        label="Push cifrado",
        description="Troca o SMS por notificação cifrada de ponta a ponta.",
        lessons=["Aula 07", "Aula 12"],
    ),
]


def catalog() -> LinkCatalog:
    return LinkCatalog(
        model_version=MODEL_VERSION,
        notice=_NOTICE,
        scenarios=_SCENARIOS,
        defenses=_DEFENSES,
    )
