"""Calcula estatísticas gerenciais a partir dos dados extraídos do AtivMob."""


def calcular_indicadores(dados):
    """Recebe os dados validados do PDF e devolve indicadores calculados."""

    pedidos = dados["pedidos"]
    areas = sorted(
        dados["areas"],
        key=lambda area: area["quantidade"],
        reverse=True,
    )
    horarios = dados["horarios"]

    if pedidos < 0:
        raise ValueError("O total de pedidos não pode ser negativo.")

    def percentual(quantidade):
        if pedidos == 0:
            return 0.0
        return round(quantidade / pedidos * 100, 1)

    maior_area = areas[0] if areas else None
    duas_maiores = sum(area["quantidade"] for area in areas[:2])

    pico = max(
        horarios,
        key=lambda item: item["quantidade"],
        default=None,
    )
    if pico is not None and pico["quantidade"] == 0:
        pico = None

    pedidos_manha = sum(
        item["quantidade"]
        for item in horarios
        if 6 <= int(item["hora"][:2]) < 12
    )

    return {
        "maior_area": maior_area,
        "participacao_maior_area": (
            percentual(maior_area["quantidade"]) if maior_area else 0.0
        ),
        "concentracao_duas": percentual(duas_maiores),
        "pico": pico,
        "participacao_pico": (
            percentual(pico["quantidade"]) if pico else 0.0
        ),
        "pedidos_manha": pedidos_manha,
        "participacao_manha": percentual(pedidos_manha),
    }