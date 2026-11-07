"""Layout-base da maquete ``casa_smart_premium_v02.glb`` para revisão pela pessoa usuária.

Coordenadas em unidades da cena 3D do frontend (o modelo é centralizado em X/Z,
apoiado em Y = 0 e escalado para 2,05 de altura em ``three/v2model.ts``). As
caixas dos ambientes foram medidas a partir dos nós ``02_Interiores`` e
``01_Arquitetura`` do GLB.

Valores intencionalmente vazios: ``budget``, ``unit_cost`` e
``installation_cost``. A otimização só roda depois que a pessoa os informa.
Estoque = 1 unidade de cada sensor do kit KS5009 (``src/inventory.ts``). O
alcance e a abertura do PIR reproduzem o simulador (``src/sim/world.ts``:
``PIR_RANGE = 1.75`` e ±55°). Sensores de vibração e inclinação são de contato:
o alcance de 0,15 representa a tolerância de montagem junto ao ponto.
"""

from modules.schemas.optimization_schemas import HomeLayout

_GROUND = 0.13
_UPPER = 0.83

TEMPLATE_LAYOUT: dict = {
    "budget": None,
    "coverage_threshold": 0.8,
    "rooms": [
        {
            "id": "sala", "name": "Sala", "glb_node": "Sala",
            "floor_y": _GROUND, "height": 0.65,
            "min_xz": [-1.29, -0.80], "max_xz": [0.21, 0.40],
            "visible_room_ids": ["cozinha", "escada"],
        },
        {
            "id": "cozinha", "name": "Cozinha", "glb_node": "Cozinha",
            "floor_y": _GROUND, "height": 0.65,
            "min_xz": [-1.29, -1.05], "max_xz": [0.21, -0.80],
            "visible_room_ids": ["sala"],
        },
        {
            "id": "garagem", "name": "Garagem", "glb_node": "Garagem",
            "floor_y": _GROUND, "height": 0.68,
            "min_xz": [0.59, -1.05], "max_xz": [1.37, 0.44],
            "visible_room_ids": [],
        },
        {
            "id": "escada", "name": "Escada", "glb_node": "Escada",
            "floor_y": 0.14, "height": 1.37,
            "min_xz": [0.21, -0.77], "max_xz": [0.59, 0.40],
            "visible_room_ids": ["sala", "estar_superior"],
        },
        {
            "id": "estar_superior", "name": "Estar superior", "glb_node": "Estar_Superior",
            "floor_y": _UPPER, "height": 0.45,
            "min_xz": [-1.25, -1.04], "max_xz": [0.62, 0.01],
            "visible_room_ids": ["escada", "varanda"],
        },
        {
            "id": "suite", "name": "Suíte", "glb_node": "Suite",
            "floor_y": _UPPER, "height": 0.45,
            "min_xz": [0.61, -0.85], "max_xz": [1.32, 0.35],
            "visible_room_ids": [],
        },
        {
            "id": "varanda", "name": "Varanda", "glb_node": "Varanda",
            "floor_y": 0.77, "height": 0.32,
            "min_xz": [-1.29, 0.04], "max_xz": [0.62, 0.59],
            "visible_room_ids": ["estar_superior"],
        },
    ],
    "critical_points": [
        {"id": "porta-entrada", "name": "Porta de entrada", "room_id": "sala",
         "position": [0.12, 0.35, 0.38], "importance": 5},
        {"id": "janela-sala", "name": "Janela da sala", "room_id": "sala",
         "position": [-0.75, 0.40, 0.36], "importance": 4},
        {"id": "circulacao-sala", "name": "Circulação da sala", "room_id": "sala",
         "position": [-0.50, 0.30, -0.20], "importance": 3},
        {"id": "fundos-cozinha", "name": "Janela dos fundos da cozinha", "room_id": "cozinha",
         "position": [-0.72, 0.38, -1.02], "importance": 4},
        {"id": "portao-garagem", "name": "Portão da garagem", "room_id": "garagem",
         "position": [0.98, 0.35, 0.42], "importance": 5},
        {"id": "escada", "name": "Escada", "room_id": "escada",
         "position": [0.40, 0.50, -0.20], "importance": 3},
        {"id": "acesso-varanda", "name": "Acesso pela varanda", "room_id": "varanda",
         "position": [-0.30, 0.95, 0.30], "importance": 4},
        {"id": "janela-suite", "name": "Janela da suíte", "room_id": "suite",
         "position": [1.00, 1.05, 0.33], "importance": 4},
        {"id": "fundos-estar", "name": "Fundos do estar superior", "room_id": "estar_superior",
         "position": [-0.30, 1.00, -1.00], "importance": 3},
    ],
    "candidate_points": [
        {"id": "pir-sala-frente", "name": "Teto da sala (frente)", "room_id": "sala",
         "position": [-1.22, 0.62, 0.33], "allowed_sensor_type_ids": ["pir"]},
        {"id": "pir-sala-fundo", "name": "Teto da sala (fundo)", "room_id": "sala",
         "position": [0.14, 0.62, -0.73], "allowed_sensor_type_ids": ["pir"]},
        {"id": "pir-cozinha", "name": "Teto da cozinha", "room_id": "cozinha",
         "position": [0.14, 0.60, -0.98], "allowed_sensor_type_ids": ["pir"]},
        {"id": "pir-garagem", "name": "Teto da garagem", "room_id": "garagem",
         "position": [1.30, 0.70, -0.98], "allowed_sensor_type_ids": ["pir"]},
        {"id": "pir-escada", "name": "Topo da escada", "room_id": "escada",
         "position": [0.40, 1.40, -0.70], "allowed_sensor_type_ids": ["pir"]},
        {"id": "pir-estar", "name": "Teto do estar superior", "room_id": "estar_superior",
         "position": [0.55, 1.20, -0.97], "allowed_sensor_type_ids": ["pir"]},
        {"id": "pir-suite", "name": "Teto da suíte", "room_id": "suite",
         "position": [1.25, 1.20, -0.78], "allowed_sensor_type_ids": ["pir"]},
        {"id": "contato-porta", "name": "Batente da porta de entrada", "room_id": "sala",
         "position": [0.12, 0.45, 0.39],
         "allowed_sensor_type_ids": ["vibracao", "inclinacao"]},
        {"id": "contato-janela-sala", "name": "Moldura da janela da sala", "room_id": "sala",
         "position": [-0.75, 0.48, 0.37],
         "allowed_sensor_type_ids": ["vibracao", "inclinacao"]},
        {"id": "contato-cozinha", "name": "Moldura da janela da cozinha", "room_id": "cozinha",
         "position": [-0.72, 0.46, -1.03],
         "allowed_sensor_type_ids": ["vibracao", "inclinacao"]},
        {"id": "contato-garagem", "name": "Trilho do portão da garagem", "room_id": "garagem",
         "position": [0.98, 0.45, 0.43],
         "allowed_sensor_type_ids": ["vibracao", "inclinacao"]},
        {"id": "contato-varanda", "name": "Porta da varanda", "room_id": "varanda",
         "position": [-0.30, 1.03, 0.30],
         "allowed_sensor_type_ids": ["vibracao", "inclinacao"]},
        {"id": "contato-suite", "name": "Moldura da janela da suíte", "room_id": "suite",
         "position": [1.00, 1.13, 0.34],
         "allowed_sensor_type_ids": ["vibracao", "inclinacao"]},
    ],
    "sensor_types": [
        {"id": "pir", "name": "Sensor de movimento PIR", "unit_cost": None,
         "installation_cost": None, "stock": 1, "range": 1.75,
         "field_of_view_deg": 110, "reliability": 1.0},
        {"id": "vibracao", "name": "Sensor de vibração", "unit_cost": None,
         "installation_cost": None, "stock": 1, "range": 0.15,
         "field_of_view_deg": 360, "reliability": 1.0},
        {"id": "inclinacao", "name": "Sensor de inclinação", "unit_cost": None,
         "installation_cost": None, "stock": 1, "range": 0.15,
         "field_of_view_deg": 360, "reliability": 1.0},
    ],
}


def template_layout() -> HomeLayout:
    return HomeLayout.model_validate(TEMPLATE_LAYOUT)
