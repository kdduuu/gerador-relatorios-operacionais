"""Relatório automático, com identidade visual configurável e dados exclusivamente da extração."""

import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from PIL import Image
from reportlab.pdfgen import canvas

from src.indicadores import calcular_indicadores
from src.ler_pdf import processar_pdf_completo

W, H = A4
M = 43
DARK = colors.HexColor("#1f1f1f")
INK = colors.HexColor("#202427")
GREY = colors.HexColor("#697279")
LIGHT = colors.HexColor("#f4f6f6")
LINE = colors.HexColor("#e2e7e5")
GREEN = colors.HexColor("#05e849")
GREEN_PALE = colors.HexColor("#e8faec")
WHITE = colors.white


def formatar_int(valor):
    return f"{valor:,}".replace(",", ".")


def formatar_pct(valor):
    return f"{valor:.1f}".replace(".", ",") + "%"


def nome_legivel(nome):
    """Preserva a escrita das categorias variáveis e normaliza nomes em caixa alta."""
    nome = str(nome).strip()
    if nome.upper() == "SAO PAULO":
        return "São Paulo"
    # Evita transformar "Retira na Loja" em "Retira Na Loja" ou alterar siglas
    # já formatadas no documento de origem. Só padroniza nomes inteiros em caps.
    legivel = nome.title() if nome.isupper() else nome
    # Faixas de distância não são unidades geográficas: preservar "km" minúsculo.
    return re.sub(r"\bKm\b", "km", legivel)


def ajustar_fonte(pdf, texto, fonte, max_largura, inicial=12, minimo=8):
    tamanho = inicial
    while pdf.stringWidth(str(texto), fonte, tamanho) > max_largura and tamanho > minimo:
        tamanho -= 0.5
    return tamanho


def txt(pdf, x, y, valor, tamanho=9, cor=INK, forte=False):
    pdf.setFillColor(cor)
    pdf.setFont("Helvetica-Bold" if forte else "Helvetica", tamanho)
    pdf.drawString(x, y, str(valor))


def txt_categoria(pdf, x, y, nome, largura, tamanho=9.2, minimo=7, forte=False, normalizar=True):
    """Desenha um nome livre do AtivMob sem invadir a coluna numérica.

    Preserva os nomes curtos em uma linha e usa duas linhas para nomes longos.
    Se um nome excepcional não couber em duas linhas, a abreviação visual
    termina em '...'; o dado integral continua no histórico JSON.
    """
    fonte = "Helvetica-Bold" if forte else "Helvetica"
    nome = nome_legivel(nome) if normalizar else str(nome)
    ajustada = ajustar_fonte(pdf, nome, fonte, largura, tamanho, minimo)
    if pdf.stringWidth(nome, fonte, ajustada) <= largura:
        txt(pdf, x, y, nome, ajustada, INK, forte)
        return

    palavras = nome.split()
    opcoes = []
    for corte in range(1, len(palavras)):
        primeira = " ".join(palavras[:corte])
        segunda = " ".join(palavras[corte:])
        largura_necessaria = max(
            pdf.stringWidth(primeira, fonte, minimo),
            pdf.stringWidth(segunda, fonte, minimo),
        )
        if largura_necessaria <= largura:
            opcoes.append((largura_necessaria, primeira, segunda))
    if opcoes:
        _, primeira, segunda = min(opcoes)
        tamanho_usado = ajustar_fonte(
            pdf, primeira if pdf.stringWidth(primeira, fonte, tamanho)
            >= pdf.stringWidth(segunda, fonte, tamanho) else segunda,
            fonte, largura, tamanho, minimo,
        )
        txt(pdf, x, y + 5, primeira, tamanho_usado, INK, forte)
        txt(pdf, x, y - 6, segunda, tamanho_usado, INK, forte)
        return

    # Truncamento visível é mais seguro que sobrepor valores de quantidade.
    abreviado = nome
    while abreviado and pdf.stringWidth(abreviado + "...", fonte, minimo) > largura:
        abreviado = abreviado[:-1]
    txt(pdf, x, y, abreviado.rstrip() + "...", minimo, INK, forte)


def txt_direita(pdf, x, y, valor, tamanho=9, cor=INK, forte=False):
    pdf.setFillColor(cor)
    pdf.setFont("Helvetica-Bold" if forte else "Helvetica", tamanho)
    pdf.drawRightString(x, y, str(valor))


def secao(pdf, y, nome, detalhe=None):
    txt(pdf, M, y, nome.upper(), 10.5, INK, True)
    if detalhe:
        txt_direita(pdf, W-M, y, detalhe, 8.2, GREY)


def arredondado(pdf, x, y, largura, altura, cor=LIGHT, raio=10):
    pdf.setFillColor(cor)
    pdf.roundRect(x, y, largura, altura, raio, fill=1, stroke=0)


def assets_path():
    # Funciona com código-fonte e com PyInstaller --onefile.
    raiz = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return raiz / "assets" / "logo.png"



def desenhar_logo(pdf, caminho):
    """Desenha uma marca opcional sem recortar o conteúdo."""
    with Image.open(caminho) as arquivo:
        imagem = arquivo.convert("RGBA")
        largura_original, altura_original = imagem.size
        escala = min(125 / largura_original, 30 / altura_original)
        pdf.drawImage(ImageReader(imagem), M + 3, H - 62,
                      width=largura_original * escala,
                      height=altura_original * escala, mask="auto")


def cabecalho(pdf, dados, numero):
    """Cabeçalho editorial compacto: marca discreta e cliente em destaque."""
    altura = 94
    pdf.setFillColor(DARK)
    pdf.rect(0, H - altura, W, altura, fill=1, stroke=0)
    pdf.setFillColor(GREEN)
    pdf.rect(0, H - 2.5, W, 2.5, fill=1, stroke=0)

    logo = assets_path()
    if logo.is_file():
        desenhar_logo(pdf, logo)
    else:
        txt(pdf, M + 3, H - 56, "RELATÓRIOS", 16, WHITE, True)

    # Três linhas são suficientes: tipo, cliente, período.
    txt_direita(pdf, W - M, H - 27, "RELATÓRIO OPERACIONAL", 9, GREEN, True)
    nome = dados["cliente"]
    fonte = ajustar_fonte(pdf, nome, "Helvetica-Bold", 255, 11.5, 8)
    txt_direita(pdf, W - M, H - 48, nome, fonte, WHITE, True)
    txt_direita(pdf, W - M, H - 67, dados["periodo"], 8.3, colors.HexColor("#c7cdca"))

    pdf.setStrokeColor(LINE)
    pdf.line(M, 57, W - M, 57)
    txt(pdf, M, 39, "Fonte: AtivMob", 7.5, GREY)
    txt_direita(pdf, W - M, 39, f"{numero}", 8, GREY, True)


def cartao(pdf, x, y, largura, titulo, numero, destaque=False):
    arredondado(pdf, x, y, largura, 72, DARK if destaque else LIGHT)
    txt(pdf, x+14, y+51, titulo.upper(), 7.6, GREEN if destaque else GREY, True)
    fonte = ajustar_fonte(pdf, numero, "Helvetica-Bold", largura-28, 23, 15)
    txt(pdf, x+14, y+17, numero, fonte, WHITE if destaque else INK, True)


def total_paginas_relatorio(dados, comparativo=None):
    """Duas páginas principais + comparativo opcional + anexos geográficos."""
    anexos_areas = max(0, (len(dados["areas"]) - 6 + 15) // 16)
    anexos_finalizacoes = max(0, (len(dados["finalizacoes"]) - 6 + 15) // 16)
    return 2 + int(comparativo is not None) + anexos_areas + anexos_finalizacoes


def pagina_executiva(pdf, dados, indicadores, total=None):
    if total is None:
        total = total_paginas_relatorio(dados)
    cabecalho(pdf, dados, f"01 / {total:02d}")
    secao(pdf, 682, "Visão geral", "Indicadores do período")
    gap = 10
    largura = (W-2*M-2*gap)/3
    entregue = dados["finalizacoes"]["Entregue"]["quantidade"]
    cartao(pdf, M, 588, largura, "Pedidos registrados", formatar_int(dados["pedidos"]), True)
    cartao(pdf, M+largura+gap, 588, largura, "Áreas identificadas", str(len(dados["areas"])))
    cartao(pdf, M+2*(largura+gap), 588, largura, "Entregas registradas", formatar_int(entregue))

    # Destaques calculados do documento, não codificados por cliente.
    arredondado(pdf, M, 514, W-2*M, 59, GREEN_PALE)
    col_w = (W-2*M)/3
    maior = indicadores["maior_area"]
    destaques = [
        ("MAIOR ÁREA", nome_legivel(maior["nome"]) if maior else "Sem dados",
         formatar_int(maior["quantidade"]) + " registros" if maior else "-"),
        ("TOP 2 ÁREAS", formatar_pct(indicadores["concentracao_duas"]), "dos pedidos do período"),
        ("PICO HORÁRIO", indicadores["pico"]["hora"],
         f'{formatar_int(indicadores["pico"]["quantidade"])} registros'),
    ]
    for i, (rot, valor, sub) in enumerate(destaques):
        x = M+13+i*col_w
        txt(pdf, x, 553, rot, 7.4, GREY, True)
        fonte = ajustar_fonte(pdf, valor, "Helvetica-Bold", col_w-23, 13, 10)
        txt(pdf, x, 534, valor, fonte, INK, True)
        txt(pdf, x, 521, sub, 7.4, GREY)

    secao(pdf, 493, "Distribuição por área", "Participação por categoria de área")
    areas = sorted(dados["areas"], key=lambda a: a["quantidade"], reverse=True)
    # Se houver muitas áreas, exibimos 6 e agrupamos as restantes; detalhes completos na página 2+.
    apresentadas = areas[:6]
    grafico = [(nome_legivel(a["nome"]), a["quantidade"]) for a in apresentadas]
    if len(areas) > 6:
        restantes = len(areas) - 6
        legenda_restantes = "Outra área" if restantes == 1 else f"Outras {restantes} áreas"
        grafico.append((legenda_restantes, sum(a["quantidade"] for a in areas[6:])))
    altura = 22 if len(grafico) <= 6 else 19
    for i, (nome, quantidade) in enumerate(grafico):
        y = 470 - i*altura
        txt_categoria(pdf, M, y, nome, 136, 8.5, 7, normalizar=False)
        base_x, base_w = 189, 230
        arredondado(pdf, base_x, y-2, base_w, 9, LIGHT, 4)
        largura_atual = base_w*quantidade/dados["pedidos"] if dados["pedidos"] else 0
        if quantidade:
            pdf.setFillColor(GREEN if i == 0 else colors.HexColor("#8e9a94"))
            pdf.roundRect(base_x, y-2, max(2, largura_atual), 9, 4, fill=1, stroke=0)
        txt_direita(pdf, W-M, y, f"{formatar_int(quantidade)}  ({formatar_pct(100*quantidade/dados['pedidos'] if dados['pedidos'] else 0)})", 8.2, INK, True)

    secao(pdf, 305, "Movimentação por horário", "Fonte: AtivMob")
    horarios = dados["horarios"]
    chart_left = M+6
    chart_bottom = 137
    chart_h = 133
    chart_w = W-2*M-12
    max_valor = max((h["quantidade"] for h in horarios), default=0)
    count = max(1, len(horarios))
    largura = chart_w / count
    for i, item in enumerate(horarios):
        valor = item["quantidade"]
        x = chart_left + i*largura + 4
        base = max(1.5, (valor/max_valor)*chart_h) if max_valor and valor else 1.5
        pdf.setFillColor(GREEN if indicadores["pico"] and item["hora"] == indicadores["pico"]["hora"] else colors.HexColor("#848f89"))
        pdf.roundRect(x, chart_bottom, largura-8, base, 2, fill=1, stroke=0)
        if i % 2 == 0:
            txt(pdf, x-1, 124, item["hora"][:2]+"h", 7, GREY)
    pico = indicadores["pico"]
    resumo_pico = (
        f'Pico: {pico["hora"]}  |  {formatar_int(pico["quantidade"])} registros  |  '
        f'{formatar_pct(indicadores["participacao_pico"])} do mês'
        if pico else "Sem registros por horário neste período."
    )
    txt(pdf, M, 95, resumo_pico, 9, INK, True)
    txt(pdf, M, 77, "As faixas horárias somam os pedidos registrados, não apenas as entregas concluídas.", 7.7, GREY)
    pdf.showPage()


def pagina_finalizacoes(pdf, dados, total=None):
    """Detalha resultados identificados, sem tempos operacionais.

    A quantidade de 'Entregue' não é uma taxa geral de sucesso.
    Os percentuais são reproduzidos do AtivMob, cuja base não é presumida.
    """
    if total is None:
        total = total_paginas_relatorio(dados)
    cabecalho(pdf, dados, f"02 / {total:02d}")
    secao(pdf, 682, "Finalizações identificadas", "Categorias legíveis do AtivMob")

    # Uma tabela única evita duplicar um grande cartão 'Entregue', que já é
    # destacado na página 1. O percentual fica em posição secundária.
    txt(pdf, M + 13, 641, "SITUAÇÃO", 7.8, GREY, True)
    txt_direita(pdf, W - M - 149, 641, "QUANTIDADE", 7.8, GREY, True)
    txt_direita(pdf, W - M - 14, 641, "PERCENTUAL ATIVMOB", 7.8, GREY, True)

    finalizacoes = list(dados["finalizacoes"].items())
    for indice, (nome, valor) in enumerate(finalizacoes[:6]):
        y = 603 - indice * 44
        entregue = nome.casefold() == "entregue"
        arredondado(pdf, M, y - 17, W - 2 * M, 36,
                    GREEN_PALE if entregue else LIGHT, 6)
        if entregue:
            pdf.setFillColor(GREEN)
            pdf.roundRect(M + 1, y - 11, 3, 24, 1.5, fill=1, stroke=0)
        txt_categoria(pdf, M + 14, y, nome, 250, 9.2, 7.5, entregue)
        txt_direita(pdf, W - M - 149, y,
                    formatar_int(valor["quantidade"]), 10, INK, True)
        txt_direita(pdf, W - M - 14, y,
                    f'{valor["percentual"]:.2f}%'.replace('.', ','), 8.6, GREY)

    # O espaço é ajustado pela quantidade de categorias: o layout comporta
    # até seis categorias sem que síntese, notas e rodapé se sobreponham.
    y_sintese = 412 - (min(len(finalizacoes), 6) - 4) * 44
    secao(pdf, y_sintese, "Síntese do período", "Leitura automática dos registros")
    arredondado(pdf, M, y_sintese - 94, W - 2 * M, 77, GREEN_PALE, 8)

    indicadores = calcular_indicadores(dados)
    frase_volume = (
        f'{formatar_int(dados["pedidos"])} pedidos em {len(dados["areas"])} áreas; '
        f'as duas maiores concentram {formatar_pct(indicadores["concentracao_duas"])} do volume.'
    )
    pico = indicadores["pico"]
    if pico:
        frase_horario = (
            f'Maior movimentação às {pico["hora"]}: '
            f'{formatar_int(pico["quantidade"])} registros '
            f'({formatar_pct(indicadores["participacao_pico"])} do período).'
        )
    else:
        frase_horario = "Não há pico horário identificável nos registros do período."

    fonte_volume = ajustar_fonte(pdf, frase_volume, "Helvetica", W - 2 * M - 28, 8.6, 7.3)
    fonte_horario = ajustar_fonte(pdf, frase_horario, "Helvetica", W - 2 * M - 28, 8.6, 7.3)
    txt(pdf, M + 14, y_sintese - 46, frase_volume, fonte_volume, INK)
    txt(pdf, M + 14, y_sintese - 69, frase_horario, fonte_horario, INK)

    y_notas = y_sintese - 126
    secao(pdf, y_notas, "Notas de leitura")
    arredondado(pdf, M, y_notas - 118, W - 2 * M, 101, LIGHT, 8)
    notas = (
        "As categorias apresentadas são somente as identificadas no PDF original.",
        "Percentuais reproduzidos do AtivMob; a base não é recalculada neste relatório.",
        "Valores ou legendas incompletos não são estimados.",
    )
    for i, frase in enumerate(notas):
        fonte = ajustar_fonte(pdf, frase, "Helvetica", W - 2 * M - 28, 8.2, 7.2)
        txt(pdf, M + 14, y_notas - 43 - i * 23, frase, fonte, GREY)
    pdf.showPage()



def _mes_legivel(competencia):
    """Legenda curta e estável dos dois meses comparados."""
    meses = ("Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez")
    ano, mes = map(int, competencia.split("-"))
    return f"{meses[mes - 1]}/{ano}"


def _variacao_legivel(item, *, incluir_diferenca=True):
    """Não apresenta percentual calculado quando a base anterior é zero."""
    diferenca = item.get("diferenca")
    pct = item.get("variacao_percentual")
    if diferenca is None:
        return "n/d"
    prefixo = f"{diferenca:+,}".replace(",", ".") if incluir_diferenca else ""
    if pct is None:
        return f"{prefixo} (base zero)" if prefixo else "base zero"
    percentual = f"{pct:+.1f}%".replace(".", ",")
    return f"{prefixo} ({percentual})" if prefixo else percentual


def pagina_comparativa(pdf, dados, comparativo, numero, total):
    """Página opcional: volumes observados em dois meses consecutivos.

    Todas as quantidades vêm de calcular_comparativo(); nenhuma taxa de
    sucesso ou indicador de tempo operacional é criado aqui.
    """
    cabecalho(pdf, dados, f"{numero:02d} / {total:02d}")
    periodo_anterior = _mes_legivel(comparativo["competencia_anterior"])
    periodo_atual = _mes_legivel(comparativo["competencia_atual"])
    secao(pdf, 682, "Comparativo mensal", f"{periodo_anterior}  x  {periodo_atual}")
    txt(pdf, M, 661,
        "Variação de registros entre competências consecutivas da mesma operação.",
        8.5, GREY)

    # Resumo do volume: nunca interpreta variação como avaliação de qualidade.
    metricas = [
        ("Pedidos registrados", comparativo["pedidos"]),
        ("Entregas registradas", comparativo["entregas_registradas"]),
        ("Áreas identificadas", comparativo["areas_atendidas"]),
    ]
    gap = 10
    largura = (W - 2 * M - 2 * gap) / 3
    for i, (titulo, item) in enumerate(metricas):
        x = M + i * (largura + gap)
        arredondado(pdf, x, 557, largura, 81, GREEN_PALE if i == 0 else LIGHT, 8)
        txt(pdf, x + 12, 616, titulo.upper(), 7.3, GREY, True)
        linha = f'{formatar_int(item["anterior"])}  /  {formatar_int(item["atual"])}'
        fonte = ajustar_fonte(pdf, linha, "Helvetica-Bold", largura - 24, 15, 10)
        txt(pdf, x + 12, 587, linha, fonte, INK, True)
        variacao = _variacao_legivel(item)
        fonte_var = ajustar_fonte(pdf, variacao, "Helvetica", largura - 24, 9.0, 7.5)
        txt(pdf, x + 12, 569, variacao, fonte_var, GREY)

    txt(pdf, M, 542, f"Leitura dos cartões: {periodo_anterior} / {periodo_atual}; abaixo, variação absoluta e percentual.", 7.3, GREY)

    secao(pdf, 513, "Distribuição por área", "Até 6 áreas com maior volume atual")
    txt(pdf, M + 9, 487, "ÁREA", 7.5, GREY, True)
    txt_direita(pdf, 338, 487, periodo_anterior.upper(), 7.4, GREY, True)
    txt_direita(pdf, 410, 487, periodo_atual.upper(), 7.4, GREY, True)
    txt_direita(pdf, W - M - 10, 487, "VARIAÇÃO", 7.4, GREY, True)

    for i, area in enumerate(comparativo["areas"][:6]):
        y = 460 - i * 29
        arredondado(pdf, M, y - 10, W - 2 * M, 25, LIGHT if i % 2 == 0 else WHITE, 4)
        txt_categoria(pdf, M + 9, y, area["nome"], 240, 8.5, 7)
        txt_direita(pdf, 338, y, formatar_int(area["anterior"]), 8.5, INK)
        txt_direita(pdf, 410, y, formatar_int(area["atual"]), 8.5, INK, True)
        texto = _variacao_legivel(area)
        fonte_delta = ajustar_fonte(pdf, texto, "Helvetica", 112, 8.0, 6.8)
        txt_direita(pdf, W - M - 10, y, texto, fonte_delta, GREY)

    concentracao = comparativo["top2_areas"]
    antes = concentracao["anterior_pct"]
    depois = concentracao["atual_pct"]
    def _p(v):
        return formatar_pct(v) if v is not None else "n/d"
    txt(pdf, M, 281,
        f"Concentração nas 2 maiores áreas: {_p(antes)} ({periodo_anterior})  /  {_p(depois)} ({periodo_atual}).",
        8.1, GREY)

    secao(pdf, 256, "Movimentação por horário", "Quantidade de pedidos por faixa")
    txt(pdf, M, 237, f"{periodo_anterior}  ", 7.5, GREY, True)
    pdf.setFillColor(colors.HexColor("#8e9a94"))
    pdf.roundRect(M + 79, 235, 17, 7, 2, fill=1, stroke=0)
    txt(pdf, M + 115, 237, f"{periodo_atual}  ", 7.5, GREY, True)
    pdf.setFillColor(GREEN)
    pdf.roundRect(M + 198, 235, 17, 7, 2, fill=1, stroke=0)

    faixas = comparativo["horarios"]
    maior = max((max(i["anterior"], i["atual"]) for i in faixas), default=0)
    chart_left, chart_bottom, chart_height = M + 4, 137, 84
    espaco = (W - 2 * M - 8) / max(len(faixas), 1)
    for i, faixa in enumerate(faixas):
        x = chart_left + i * espaco
        for j, (valor, cor) in enumerate((
            (faixa["anterior"], colors.HexColor("#8e9a94")),
            (faixa["atual"], GREEN),
        )):
            if valor > 0 and maior > 0:
                altura = max(1.5, valor / maior * chart_height)
                pdf.setFillColor(cor)
                pdf.roundRect(x + 4 + j * 8, chart_bottom, 7, altura, 2, fill=1, stroke=0)
        if i % 2 == 0:
            txt(pdf, x + 2, 123, faixa["hora"][:2] + "h", 7, GREY)

    def _pico(pico):
        if pico is None:
            return "sem pico"
        return f'{pico["hora"]}: {formatar_int(pico["quantidade"])} registros'

    resumo = f"Picos: {periodo_anterior} - {_pico(comparativo['pico_anterior'])}; {periodo_atual} - {_pico(comparativo['pico_atual'])}."
    txt(pdf, M, 104,
        resumo, ajustar_fonte(pdf, resumo, "Helvetica", W - 2 * M, 8, 7.2), INK)
    txt(pdf, M, 84,
        "Variações descrevem volume, não qualidade. Base anterior zero: percentual não calculável.",
        7.4, GREY)
    pdf.showPage()


def paginas_adicionais(pdf, dados, total=None, inicio=3):
    """Lista categorias de área não detalhadas no gráfico da página 1.

    Não exibe colunas operacionais de duração, mesmo para muitas áreas.
    """
    areas = sorted(dados["areas"], key=lambda area: area["quantidade"], reverse=True)
    adicionais = areas[6:]
    if not adicionais:
        return
    grupos = [adicionais[i:i + 16] for i in range(0, len(adicionais), 16)]
    if total is None:
        total = total_paginas_relatorio(dados)
    for numero, grupo in enumerate(grupos, start=inicio):
        cabecalho(pdf, dados, f"{numero:02d} / {total:02d}")
        secao(pdf, 682, "Distribuição por área — continuação", "Demais categorias de área")
        arredondado(pdf, M, 635, W - 2 * M, 30, LIGHT, 5)
        txt(pdf, M + 12, 645, "ÁREA", 7.8, GREY, True)
        txt_direita(pdf, W - M - 112, 645, "PEDIDOS", 7.8, GREY, True)
        txt_direita(pdf, W - M - 12, 645, "PARTICIPAÇÃO", 7.8, GREY, True)
        for indice, area in enumerate(grupo):
            y = 607 - indice * 32
            txt_categoria(pdf, M + 12, y, area["nome"], 295, 9, 7)
            txt_direita(pdf, W - M - 112, y, formatar_int(area["quantidade"]), 9, INK, True)
            pct = (area["quantidade"] / dados["pedidos"] * 100) if dados["pedidos"] else 0
            txt_direita(pdf, W - M - 12, y, formatar_pct(pct), 9, GREY)
            pdf.setStrokeColor(LINE)
            pdf.line(M + 10, y - 10, W - M - 10, y - 10)
        pdf.showPage()


def paginas_finalizacoes_adicionais(pdf, dados, total, inicio):
    """Mostra todas as legendas completas que ultrapassaram as seis iniciais."""
    restantes = list(dados["finalizacoes"].items())[6:]
    for pagina_indice, deslocamento in enumerate(range(0, len(restantes), 16)):
        numero = inicio + pagina_indice
        cabecalho(pdf, dados, f"{numero:02d} / {total:02d}")
        secao(pdf, 682, "Finalizações — continuação", "Demais categorias legíveis do AtivMob")
        arredondado(pdf, M, 635, W - 2 * M, 30, LIGHT, 5)
        txt(pdf, M + 12, 645, "SITUAÇÃO", 7.8, GREY, True)
        txt_direita(pdf, W - M - 145, 645, "QUANTIDADE", 7.8, GREY, True)
        txt_direita(pdf, W - M - 12, 645, "PERCENTUAL ATIVMOB", 7.5, GREY, True)
        for i, (nome, valor) in enumerate(restantes[deslocamento:deslocamento + 16]):
            y = 607 - 32 * i
            txt_categoria(pdf, M + 12, y, nome, 260, 8.8, 6.5)
            txt_direita(pdf, W - M - 145, y, formatar_int(valor["quantidade"]), 9, INK, True)
            txt_direita(pdf, W - M - 12, y, f'{valor["percentual"]:.2f}%'.replace('.', ','), 8.8, GREY)
            pdf.setStrokeColor(LINE)
            pdf.line(M + 10, y - 10, W - M - 10, y - 10)
        pdf.showPage()


def gerar_relatorio(dados, destino, comparativo=None):
    """Gera duas páginas padrão; acrescenta comparação apenas quando informada.

    A interface antiga continua compatível com gerar_relatorio(dados, destino).
    O cálculo do comparativo é feito antes, por src.comparativo.
    """
    if comparativo is not None:
        # Impede usar por engano o comparativo de outra operação/competência.
        if comparativo["operacao"] != dados["cliente"]:
            raise ValueError("O comparativo pertence a outra operação.")
        data_atual = datetime.strptime(dados["periodo"][:10], "%d/%m/%Y")
        competencia_atual = data_atual.strftime("%Y-%m")
        anterior = (data_atual - timedelta(days=1)).strftime("%Y-%m")
        if (comparativo["competencia_atual"] != competencia_atual
                or comparativo["competencia_anterior"] != anterior):
            raise ValueError("As competências do comparativo não correspondem ao PDF.")
        if comparativo["pedidos"]["atual"] != dados["pedidos"]:
            raise ValueError("Total do comparativo diferente do PDF atual.")

    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    total = total_paginas_relatorio(dados, comparativo)
    indicadores = calcular_indicadores(dados)
    arquivo = canvas.Canvas(str(destino), pagesize=A4)
    arquivo.setTitle(f"Acompanhamento operacional - {dados['cliente']} - {dados['periodo']}")
    pagina_executiva(arquivo, dados, indicadores, total)
    pagina_finalizacoes(arquivo, dados, total)
    if comparativo is not None:
        pagina_comparativa(arquivo, dados, comparativo, 3, total)
    primeiro_anexo = 4 if comparativo is not None else 3
    paginas_adicionais(arquivo, dados, total, inicio=primeiro_anexo)
    anexos_areas = max(0, (len(dados["areas"]) - 6 + 15) // 16)
    paginas_finalizacoes_adicionais(arquivo, dados, total, primeiro_anexo + anexos_areas)
    arquivo.save()
    return destino


def nome_sugerido(dados):
    competencia = datetime.strptime(dados["periodo"][:10], "%d/%m/%Y").strftime("%Y-%m")
    identificador = re.sub(r"[^\w-]+", "_", dados["cliente"], flags=re.UNICODE).strip("_")
    return f"Relatorio_{identificador}_{competencia}.pdf"


def main():
    arquivos = list(Path("dados/entrada").glob("*.pdf"))
    if len(arquivos) != 1:
        raise SystemExit("Coloque um único PDF na pasta dados/entrada ou utilize a interface Windows.")
    dados = processar_pdf_completo(arquivos[0])
    saida = gerar_relatorio(dados, Path("dados/saida")/nome_sugerido(dados))
    print(f"Relatório gerado: {saida}")
    if dados["avisos"]:
        print("AVISO: algumas finalizações estão truncadas no PDF original.")


if __name__ == "__main__":
    main()
