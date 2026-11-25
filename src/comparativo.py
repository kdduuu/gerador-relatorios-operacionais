"""Compara competências consecutivas da mesma operação.

Recebe o PDF atual já extraído e o registro anterior vindo de
Historico.mes_anterior(). Não acessa rede, altera históricos nem gera PDF.
Valores ausentes nas finalizações nunca são interpretados como zero.
"""

import unicodedata
from datetime import date, timedelta

from src.historico import ErroHistorico, _resumo
from src.indicadores import calcular_indicadores


class ErroComparativo(ValueError):
    """Dados não comparáveis ou inconsistentes."""


def _chave_nome(nome):
    """Permite reconhecer 'SAO PAULO' e 'SÃO PAULO' como uma só área."""
    base = " ".join(str(nome).split()).casefold()
    base = unicodedata.normalize("NFKD", base)
    return "".join(letra for letra in base if not unicodedata.combining(letra))


def _mapa(itens, campo, *, dicionario=False):
    """Indexa por nome normalizado sem mesclar duplicidades em silêncio."""
    resultado = {}
    origem = (
        ({"nome": nome, **valor} for nome, valor in itens.items())
        if dicionario else itens
    )
    for item in origem:
        nome = item["nome"]
        chave = _chave_nome(nome)
        if not chave or chave in resultado:
            raise ErroComparativo(f"{campo}: nome ausente ou duplicado: {nome!r}.")
        resultado[chave] = item
    return resultado


def _diferenca(atual, anterior):
    """Variação percentual é indefinida quando a base anterior é zero."""
    if atual is None or anterior is None:
        return {
            "anterior": anterior, "atual": atual,
            "diferenca": None, "variacao_percentual": None,
        }
    return {
        "anterior": anterior,
        "atual": atual,
        "diferenca": atual - anterior,
        "variacao_percentual": (
            round((atual - anterior) * 100 / anterior, 1)
            if anterior != 0 else None
        ),
    }


def _competencia_anterior(competencia):
    ano, mes = map(int, competencia.split("-"))
    return (date(ano, mes, 1) - timedelta(days=1)).strftime("%Y-%m")


def _validar_anterior(registro):
    """Revalida os dados armazenados, inclusive identidade e competência."""
    try:
        dados = {
            "cliente": registro["operacao"],
            "periodo": registro["periodo"],
            "pedidos": registro["pedidos"],
            "areas": registro["areas"],
            "horarios": registro["horarios"],
            "finalizacoes": registro["finalizacoes"],
        }
        validado = _resumo(dados)
        for campo in ("versao", "identificador", "competencia", "operacao"):
            if registro[campo] != validado[campo]:
                raise ErroComparativo(f"Registro anterior com {campo} inconsistente.")
        return validado
    except (KeyError, TypeError, AttributeError, ErroHistorico) as erro:
        raise ErroComparativo("Registro anterior incompleto ou inválido.") from erro


def calcular_comparativo(dados_atuais, registro_anterior):
    """Devolve indicadores comparáveis ou None quando não há mês anterior.

    A consulta do mês anterior deve ser feita por Historico.mes_anterior;
    não é necessário que o operador selecione um segundo PDF.
    """
    if registro_anterior is None:
        return None
    try:
        atual = _resumo(dados_atuais)
    except (ErroHistorico, KeyError, TypeError) as erro:
        raise ErroComparativo("Dados do mês atual inválidos para comparação.") from erro
    anterior = _validar_anterior(registro_anterior)
    if atual["identificador"] != anterior["identificador"]:
        raise ErroComparativo("Não é permitido comparar operações diferentes.")
    if anterior["competencia"] != _competencia_anterior(atual["competencia"]):
        raise ErroComparativo("A comparação exige meses consecutivos, na ordem correta.")

    areas_atual = _mapa(atual["areas"], "Áreas")
    areas_anterior = _mapa(anterior["areas"], "Áreas")
    final_atual = _mapa(atual["finalizacoes"], "Finalizações", dicionario=True)
    final_anterior = _mapa(anterior["finalizacoes"], "Finalizações", dicionario=True)
    chave_entregue = _chave_nome("Entregue")
    if chave_entregue not in final_atual or chave_entregue not in final_anterior:
        raise ErroComparativo("Categoria Entregue não identificada nos dois períodos.")

    horas_atuais = {i["hora"]: i["quantidade"] for i in atual["horarios"]}
    horas_anteriores = {i["hora"]: i["quantidade"] for i in anterior["horarios"]}
    horas_esperadas = {f"{hora:02d}:00" for hora in range(6, 24)}
    if set(horas_atuais) != horas_esperadas or set(horas_anteriores) != horas_esperadas:
        raise ErroComparativo("Faixas horárias incompletas ou inesperadas.")

    areas = []
    for chave in areas_atual.keys() | areas_anterior.keys():
        a = areas_atual.get(chave)
        b = areas_anterior.get(chave)
        # Uma área que não aparece no outro mês tem zero pedidos registrados
        # naquela área, dado que o total completo por área foi validado.
        qtd_atual = a["quantidade"] if a is not None else 0
        qtd_anterior = b["quantidade"] if b is not None else 0
        areas.append({
            "nome": (a or b)["nome"],
            **_diferenca(qtd_atual, qtd_anterior),
        })
    areas.sort(key=lambda item: (-item["atual"], item["nome"].casefold()))

    finalizacoes = []
    for chave in final_atual.keys() | final_anterior.keys():
        a = final_atual.get(chave)
        b = final_anterior.get(chave)
        finalizacoes.append({
            "nome": (a or b)["nome"],
            **_diferenca(
                a["quantidade"] if a is not None else None,
                b["quantidade"] if b is not None else None,
            ),
            "comparavel": a is not None and b is not None,
        })
    finalizacoes.sort(
        key=lambda item: (item["nome"].casefold() != "entregue", item["nome"].casefold())
    )

    ind_atual = calcular_indicadores(atual)
    ind_anterior = calcular_indicadores(anterior)
    top2_atual = ind_atual["concentracao_duas"] if atual["pedidos"] else None
    top2_anterior = ind_anterior["concentracao_duas"] if anterior["pedidos"] else None

    return {
        "operacao": atual["operacao"],
        "competencia_atual": atual["competencia"],
        "competencia_anterior": anterior["competencia"],
        "pedidos": _diferenca(atual["pedidos"], anterior["pedidos"]),
        "areas_atendidas": _diferenca(len(atual["areas"]), len(anterior["areas"])),
        "entregas_registradas": _diferenca(
            final_atual[chave_entregue]["quantidade"],
            final_anterior[chave_entregue]["quantidade"],
        ),
        "top2_areas": {
            "anterior_pct": top2_anterior,
            "atual_pct": top2_atual,
            "variacao_pontos_percentuais": (
                round(top2_atual - top2_anterior, 1)
                if top2_atual is not None and top2_anterior is not None else None
            ),
        },
        "pico_anterior": ind_anterior["pico"],
        "pico_atual": ind_atual["pico"],
        "areas": areas,
        "finalizacoes": finalizacoes,
        "horarios": [
            {"hora": hora, **_diferenca(horas_atuais[hora], horas_anteriores[hora])}
            for hora in sorted(horas_esperadas)
        ],
    }
