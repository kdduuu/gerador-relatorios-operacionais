import re
from pathlib import Path

import pymupdf

# O AtivMob pode usar categorias diferentes em cada operação. Não manter
# uma lista fechada de nomes: usamos apenas o formato da legenda do gráfico.
PADRAO_CATEGORIA_COMPLETA = re.compile(
    r"(?P<nome>.+?)\s*\(\s*"
    r"(?P<quantidade>\d{1,3}(?:\.\d{3})+|\d+)\s*-\s*"
    r"(?P<percentual>\d{1,3}(?:[,.]\d{1,2})?)\s*%\s*\)",
    re.IGNORECASE,
)
PADRAO_CATEGORIA_TRUNCADA = re.compile(
    r"(?P<nome>.+?)(?:\s*\(\s*\d[\d.]*)?\s*(?:\u2026|\.\.\.)$"
)


def ler_paginas(caminho):
    """Lê as duas páginas que contêm os indicadores principais."""
    with pymupdf.open(caminho) as documento:
        if len(documento) < 2:
            raise ValueError("O PDF precisa ter pelo menos duas páginas.")
        return documento[0].get_text(), documento[1].get_text()


def extrair_areas(texto):
    """Organiza a tabela da primeira página em uma lista de dicionários."""
    linhas = [linha.strip() for linha in texto.splitlines() if linha.strip()]

    if not linhas or not re.fullmatch(r"\d{2}/\d{2}/\d{4} a \d{2}/\d{2}/\d{4}", linhas[0]):
        raise ValueError("Período não encontrado no formato esperado.")

    if "Espera total cliente" not in linhas:
        raise ValueError("Tabela operacional não encontrada.")

    inicio = linhas.index("Espera total cliente") + 1
    fim = next((i for i in range(inicio, len(linhas)) if linhas[i].startswith("Separação:")), None)
    if fim is None:
        raise ValueError("Final da tabela não encontrado.")

    valores = linhas[inicio:fim]
    if not valores or len(valores) % 6 != 0:
        raise ValueError("Tabela de áreas vazia ou incompleta.")

    areas = []
    for i in range(0, len(valores), 6):
        nome, quantidade, separacao, roteirizacao, rota, espera = valores[i:i + 6]
        if not quantidade.isdigit():
            raise ValueError(f"Quantidade inválida em {nome}.")
        if not all(re.fullmatch(r"\d{2}:[0-5]\d", tempo) for tempo in (separacao, roteirizacao, rota, espera)):
            raise ValueError(f"Tempo operacional inválido em {nome}.")
        areas.append({
            "nome": nome,
            "quantidade": int(quantidade),
            "separacao": separacao,
            "roteirizacao": roteirizacao,
            "rota": rota,
            "espera": espera,
        })
    return linhas[0], areas


def extrair_total_pedidos(texto):
    """Busca a quantidade de pedidos informada na segunda página."""
    resultado = re.search(r"Número de pedidos\s*\(\s*(\d+)\s*\)", texto)
    if resultado is None:
        raise ValueError("Total de pedidos não encontrado na página 2.")
    return int(resultado.group(1))


def extrair_finalizacoes(texto):
    """Lê as legendas *da seção Finalizações* sem lista fixa de categorias.

    Cada legenda completa deve ter nome (quantidade - percentual%). O AtivMob
    quebra nomes e valores entre linhas; reunimos até três linhas consecutivas.
    Legendas truncadas e 'Other' são sinalizadas, nunca convertidas em zero.
    A seção de cadastro (após 'Número de pedidos') não entra nesta leitura.
    """
    inicio = re.search(r"Finaliza(?:ções|coes)", texto, re.IGNORECASE)
    if inicio is None:
        raise ValueError("Seção Finalizações não encontrada no PDF.")
    fim = re.search(r"Número de pedidos", texto[inicio.end():], re.IGNORECASE)
    if fim is None:
        raise ValueError("Fim da seção Finalizações não encontrado no PDF.")
    trecho = texto[inicio.end():inicio.end() + fim.start()]
    linhas = [linha.strip() for linha in trecho.splitlines() if linha.strip()]
    finalizacoes = {}
    avisos = []
    i = 0
    while i < len(linhas):
        # A legenda genérica "Other"/"Outros" pode aparecer isolada junto
        # ao gráfico. Não a juntar com o nome da categoria seguinte.
        # Se a linha seguinte começa com "(", ela pode ser uma categoria
        # legítima, com quantidade e percentual quebrados em outra linha.
        linha_atual = linhas[i]
        if (linha_atual.casefold() in {"other", "outros"}
                and (i + 1 == len(linhas) or not linhas[i + 1].startswith("("))):
            avisos.append(f"{linha_atual}: legenda sem valores completos no PDF.")
            i += 1
            continue

        encontrada = False
        # Ex.: 'Não Entregue (29' + '- 0,75%)'; ou 'Produto Incorreto' + '(7 - 0,50%)'.
        for quantidade_linhas in range(1, min(6, len(linhas) - i) + 1):
            partes = linhas[i:i + quantidade_linhas]
            # Uma reticência indica legenda truncada, não uma continuação do
            # nome seguinte. Nunca atravessá-la tentando achar um percentual.
            if any("…" in parte or "..." in parte for parte in partes):
                break
            candidato = " ".join(partes)
            match = PADRAO_CATEGORIA_COMPLETA.fullmatch(candidato)
            if not match:
                continue
            nome = " ".join(match.group("nome").split())
            # Evita que uma legenda numérica incompleta ("Troca (2") seja
            # engolida pela próxima legenda completa; parênteses em nomes
            # válidos, como "Retira (Loja)", continuam aceitos.
            if (not any(caractere.isalpha() for caractere in nome)
                    or nome.count("(") != nome.count(")")):
                continue
            if nome.casefold() == "entregue":
                nome = "Entregue"  # chave esperada pelos cartões do relatório
            quantidade = int(match.group("quantidade").replace(".", ""))
            percentual = float(match.group("percentual").replace(",", "."))
            if not 0 <= percentual <= 100:
                raise ValueError(f"Percentual inválido na finalização: {nome}.")
            if any(ja.casefold() == nome.casefold() for ja in finalizacoes):
                raise ValueError(f"Categoria de finalização repetida: {nome}.")
            finalizacoes[nome] = {"quantidade": quantidade, "percentual": percentual}
            i += quantidade_linhas
            encontrada = True
            break
        if encontrada:
            continue

        # Legenda incompleta pode também ter nome repartido entre duas linhas.
        for quantidade_linhas in range(1, min(6, len(linhas) - i) + 1):
            candidato = " ".join(linhas[i:i + quantidade_linhas])
            match = PADRAO_CATEGORIA_TRUNCADA.fullmatch(candidato)
            if not match:
                continue
            nome = " ".join(match.group("nome").split())
            if any(letra.isalpha() for letra in nome):
                avisos.append(f"{nome}: legenda truncada; quantidade indisponível no PDF.")
                i += quantidade_linhas
                encontrada = True
                break
        if encontrada:
            continue

        # Um rótulo alfabético que sobrou nesta seção é uma legenda sem valores
        # completos (incluindo 'Other' e 'Outros'), nunca um valor zero.
        if any(letra.isalpha() for letra in linhas[i]):
            avisos.append(f"{linhas[i]}: legenda sem valores completos no PDF.")
        i += 1

    if "Entregue" not in finalizacoes:
        raise ValueError(
            "Categoria Entregue não encontrada com quantidade e percentual completos. "
            "Confirme como o AtivMob identifica as entregas nesta operação."
        )
    return finalizacoes, avisos


def processar_pdf(caminho):
    """Coordena leitura, extração e conferência dos totais."""
    pagina_1, pagina_2 = ler_paginas(caminho)
    periodo, areas = extrair_areas(pagina_1)
    pedidos = extrair_total_pedidos(pagina_2)
    total_areas = sum(area["quantidade"] for area in areas)

    if total_areas != pedidos:
        raise ValueError(f"Divergência: {total_areas} por área, mas {pedidos} pedidos no relatório.")

    finalizacoes, avisos = extrair_finalizacoes(pagina_2)
    return {
        "periodo": periodo,
        "areas": areas,
        "pedidos": pedidos,
        "finalizacoes": finalizacoes,
        "avisos": avisos,
    }


def main():
    arquivos = list(Path("dados/entrada").glob("*.pdf"))
    if len(arquivos) != 1:
        raise SystemExit("Coloque exatamente um PDF em dados/entrada.")

    try:
        relatorio = processar_pdf_completo(arquivos[0])
    except ValueError as erro:
        raise SystemExit(f"Erro na validação: {erro}") from erro

    print(f'Cliente: {relatorio["cliente"]}')
    print(f'Período: {relatorio["periodo"]}\n')
    for area in relatorio["areas"]:
        print(f'Área: {area["nome"]}')
        print(f'Quantidade: {area["quantidade"]}')
        print(f'Separação: {area["separacao"]}')
        print(f'Roteirização: {area["roteirizacao"]}')
        print(f'Rota: {area["rota"]}')
        print(f'Espera: {area["espera"]}\n')

    print(f'Total de registros por área: {sum(a["quantidade"] for a in relatorio["areas"])}')
    print(f'Total de pedidos: {relatorio["pedidos"]}')
    print("Validação dos totais: OK\n")

    print("--- FINALIZAÇÕES ---")
    for categoria, valor in relatorio["finalizacoes"].items():
        percentual = f'{valor["percentual"]:.2f}'.replace(".", ",")
        print(f'{categoria}: {valor["quantidade"]} ({percentual}%)')

    for aviso in relatorio["avisos"]:
        print(f"ATENÇÃO: {aviso}")

    print("\n--- TEMPOS GERAIS ---")
    for nome, tempo in relatorio["tempos_gerais"].items():
        print(f"{nome.title()}: {tempo}")

    print("\n--- REGISTROS POR HORÁRIO ---")
    for item in relatorio["horarios"]:
        print(f'{item["hora"]}: {item["quantidade"]}')
    print(f'Pico: {relatorio["pico_horario"]["hora"]} ({relatorio["pico_horario"]["quantidade"]})')
    print("Conferência dos horários: OK")

    print("\nObservação: percentuais extraídos do AtivMob, não calculados sobre o total de pedidos.")


def extrair_cliente(texto):
    """Identifica a operação no cabeçalho do relatório AtivMob."""
    resultado = re.search(
        r"\d{2}/\d{2}/\d{4},\s*\d{2}:\d{2}\s*\n([^\n]+)",
        texto,
    )
    if resultado is None:
        raise ValueError("Nome da operação não identificado no PDF.")
    return resultado.group(1).strip()


def extrair_tempos_gerais(texto):
    """Lê os valores gerais da primeira página, sem recalcular médias."""
    resultado = re.search(
        r"Separação:\s*(\d{2}:\d{2})\s*;\s*"
        r"Rota:\s*(\d{2}:\d{2})\s*;\s*"
        r"Espera do cliente:\s*(\d{2}:\d{2})",
        texto,
    )
    if resultado is None:
        raise ValueError("Tempos gerais não encontrados na página 1.")
    return dict(zip(("separacao", "rota", "espera"), resultado.groups()))


def extrair_cadastro(texto):
    """Extrai a classificação de cadastro indicada pelo sistema."""
    resultado = re.search(
        r"Manual\s*\(\s*(\d+)\s*-\s*(\d+[,.]\d+)%\s*\)",
        " ".join(texto.split()),
        re.IGNORECASE,
    )
    if resultado is None:
        return None  # Ausência não é igual a zero.
    return {
        "manual": int(resultado.group(1)),
        "percentual": float(resultado.group(2).replace(",", ".")),
    }


def extrair_distribuicao_horaria(pagina):
    """Lê os rótulos do gráfico da página 3 pela posição na página.

    O PDF repete visualmente alguns rótulos (ex.: 193 três vezes).
    Para cada faixa horária conservamos um único valor e verificamos conflitos.
    """
    palavras = pagina.get_text("words", sort=False)
    eixos = []
    for item in palavras:
        x0, y0, x1, y1, texto = item[:5]
        if (re.fullmatch(r"(?:0[68]|1[02468]|20|22):00", texto)
                and 50 < x0 < 100 and 45 < y0 < 500):
            eixos.append((int(texto[:2]), (y0 + y1) / 2, x1))

    marca_06 = next((e for e in eixos if e[0] == 6), None)
    marca_08 = next((e for e in eixos if e[0] == 8), None)
    if marca_06 is None or marca_08 is None:
        raise ValueError("Eixo horário da página 3 não reconhecido.")

    passo = (marca_06[1] - marca_08[1]) / 2
    if passo <= 0:
        raise ValueError("Escala horária inválida na página 3.")

    limite_esquerdo = max(e[2] for e in eixos) + 5
    valores = {}

    for item in palavras:
        x0, y0, x1, y1, texto = item[:5]
        if not texto.isdigit() or x0 <= limite_esquerdo:
            continue

        centro = (y0 + y1) / 2
        deslocamento = (marca_06[1] - centro) / passo
        indice = round(deslocamento)
        hora = 6 + indice

        if not (6 <= hora <= 23) or abs(deslocamento - indice) > 0.28:
            continue

        quantidade = int(texto)
        if hora in valores and valores[hora] != quantidade:
            raise ValueError(f"Valores conflitantes no gráfico às {hora:02d}h.")
        valores[hora] = quantidade

    # Um zero omitido não pode ser presumido; cada horário deve ter seu rótulo.
    faltantes = [f"{hora:02d}h" for hora in range(6, 24) if hora not in valores]
    if faltantes:
        raise ValueError("Valores horários ausentes: " + ", ".join(faltantes))

    return [{"hora": f"{hora:02d}:00", "quantidade": valores[hora]}
            for hora in range(6, 24)]


def processar_pdf_completo(caminho):
    """Complementa o extrator validado com dados gerenciais das 3 páginas."""
    resultado = processar_pdf(caminho)

    with pymupdf.open(caminho) as documento:
        if len(documento) < 3:
            raise ValueError("O relatório AtivMob precisa conter três páginas.")
        pagina_1 = documento[0].get_text()
        pagina_2 = documento[1].get_text()
        pagina_3 = documento[2]

        resultado["cliente"] = extrair_cliente(pagina_1)
        resultado["tempos_gerais"] = extrair_tempos_gerais(pagina_1)
        resultado["cadastro"] = extrair_cadastro(pagina_2)
        resultado["horarios"] = extrair_distribuicao_horaria(pagina_3)

    soma_horarios = sum(item["quantidade"] for item in resultado["horarios"])
    if soma_horarios != resultado["pedidos"]:
        raise ValueError(
            f"Divergência horária: {soma_horarios} registros por hora "
            f"e {resultado['pedidos']} pedidos no relatório."
        )

    resultado["pico_horario"] = max(
        resultado["horarios"], key=lambda item: item["quantidade"]
    )
    return resultado


if __name__ == "__main__":
    main()