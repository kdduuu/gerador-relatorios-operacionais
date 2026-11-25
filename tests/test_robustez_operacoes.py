"""Regressões sintéticas para nomenclaturas variáveis e relatórios multicliente.

Somente dados fictícios. Não depende do servidor nem de PDFs corporativos.
"""

import tempfile
import unittest
from pathlib import Path

import pymupdf

from src.gerar_relatorio import gerar_relatorio, total_paginas_relatorio
from src.ler_pdf import extrair_finalizacoes


def dados_ficticios(*, areas=7, finalizacoes=None):
    nomes = finalizacoes or {
        "Entregue": {"quantidade": 65, "percentual": 65.0},
        "Pendente": {"quantidade": 35, "percentual": 35.0},
    }
    distribuicao = [100 // areas] * areas
    distribuicao[-1] += 100 - sum(distribuicao)
    return {
        "cliente": "CLIENTE FICTÍCIO - NOMES VARIÁVEIS",
        "periodo": "01/10/2026 a 31/10/2026",
        "pedidos": 100,
        "areas": [{"nome": f"BAIRRO FICTICIO {i:02d}", "quantidade": n}
                  for i, n in enumerate(distribuicao)],
        "horarios": [{"hora": f"{h:02d}:00", "quantidade": 100 if h == 11 else 0}
                     for h in range(6, 24)],
        "finalizacoes": nomes,
        "avisos": [],
    }


class TestRobustezOperacoes(unittest.TestCase):
    def test_other_isolado_nao_vira_prefixo_da_categoria_seguinte(self):
        texto = (
            "Finalizações\nEntregue (5 - 50,00%)\n"
            "Other\nTroca (5 - 50,00%)\nNúmero de pedidos (10)"
        )
        resultado, avisos = extrair_finalizacoes(texto)
        self.assertIn("Troca", resultado)
        self.assertNotIn("Other Troca", resultado)
        self.assertTrue(any("Other" in aviso for aviso in avisos))

    def test_legenda_truncada_nao_absorve_categoria_seguinte(self):
        texto = (
            "Finalizações\nEntregue (10 - 50%)\n"
            "COLETA\nREALIZADA (2…\n"
            "Cancelado (6\n- 30%)\n"
            "Troca (4 - 20%)\nNúmero de pedidos (20)"
        )
        resultado, avisos = extrair_finalizacoes(texto)
        self.assertEqual(set(resultado), {"Entregue", "Cancelado", "Troca"})
        self.assertTrue(any("COLETA REALIZADA" in aviso for aviso in avisos))

    def test_numero_incompleto_nao_gruda_ao_proximo_nome(self):
        texto = (
            "Finalizações\nEntregue (5 - 50%)\n"
            "Aguardando (2\nTroca (5 - 50%)\nNúmero de pedidos (10)"
        )
        resultado, avisos = extrair_finalizacoes(texto)
        self.assertIn("Troca", resultado)
        self.assertNotIn("Aguardando (2 Troca", resultado)
        self.assertTrue(avisos)

    def test_categoria_com_parenteses_no_nome(self):
        texto = (
            "Finalizações\nEntregue (4 - 40,00%)\n"
            "Retira (Loja) (6 - 60,00%)\nNúmero de pedidos (10)"
        )
        resultado, avisos = extrair_finalizacoes(texto)
        self.assertEqual(resultado["Retira (Loja)"], {"quantidade": 6, "percentual": 60.0})
        self.assertEqual(avisos, [])

    def test_categoria_em_cinco_linhas(self):
        texto = (
            "Finalizações\nEntregue (5 - 50%)\n"
            "Aguardando\nRetirada\nPelo Cliente\n(5\n- 50%)\n"
            "Número de pedidos (10)"
        )
        resultado, avisos = extrair_finalizacoes(texto)
        self.assertIn("Aguardando Retirada Pelo Cliente", resultado)
        self.assertEqual(avisos, [])

    def test_outros_com_valores_completos_e_categoria_verdadeira(self):
        texto = (
            "Finalizações\nEntregue (5 - 50%)\nOutros\n(5 - 50%)\n"
            "Número de pedidos (10)"
        )
        resultado, avisos = extrair_finalizacoes(texto)
        self.assertIn("Outros", resultado)
        self.assertEqual(avisos, [])

    def test_truncamento_continua_sendo_aviso_sem_estimar_quantidade(self):
        texto = (
            "Finalizações\nEntregue (8 - 80%)\n"
            "Recolhimento de (2…\nOther\n"
            "Número de pedidos (10)"
        )
        resultado, avisos = extrair_finalizacoes(texto)
        self.assertEqual(list(resultado), ["Entregue"])
        self.assertTrue(any("Recolhimento" in aviso for aviso in avisos))
        self.assertTrue(any("Other" in aviso for aviso in avisos))

    def test_duplicidade_de_finalizacao_continua_bloqueada(self):
        texto = (
            "Finalizações\nEntregue (5 - 50%)\nentregue (5 - 50%)\n"
            "Número de pedidos (10)"
        )
        with self.assertRaisesRegex(ValueError, "repetida"):
            extrair_finalizacoes(texto)

    def test_singular_outras_areas_e_rodape_paginado(self):
        dados = dados_ficticios(areas=7)
        with tempfile.TemporaryDirectory() as tmp:
            destino = gerar_relatorio(dados, Path(tmp) / "resultado.pdf")
            with pymupdf.open(destino) as pdf:
                self.assertEqual(len(pdf), 3)
                self.assertIn("Outra área", pdf[0].get_text())
                self.assertNotIn("Outras 1 áreas", pdf[0].get_text())
                self.assertIn("03 / 03", pdf[2].get_text())

    def test_plural_outras_areas(self):
        dados = dados_ficticios(areas=8)
        with tempfile.TemporaryDirectory() as tmp:
            destino = gerar_relatorio(dados, Path(tmp) / "resultado.pdf")
            with pymupdf.open(destino) as pdf:
                self.assertIn("Outras 2 áreas", pdf[0].get_text())

    def test_nomes_largos_aparecem_sem_sumir_e_paginas_completas(self):
        categorias = {
            "Entregue": {"quantidade": 55, "percentual": 55.0},
            "Retirada e devolução programada pelo cliente": {"quantidade": 10, "percentual": 10.0},
            "Solicitação em análise técnica": {"quantidade": 10, "percentual": 10.0},
            "Transferência para nova unidade": {"quantidade": 10, "percentual": 10.0},
            "Troca (Peça com defeito)": {"quantidade": 5, "percentual": 5.0},
            "Retira na Loja": {"quantidade": 5, "percentual": 5.0},
            "Devolução Confirmada": {"quantidade": 5, "percentual": 5.0},
        }
        dados = dados_ficticios(areas=7, finalizacoes=categorias)
        dados["areas"][0]["nome"] = "RIBEIRAO PIRES BAIRRO INDUSTRIAL LONGO"
        with tempfile.TemporaryDirectory() as tmp:
            destino = gerar_relatorio(dados, Path(tmp) / "resultado.pdf")
            with pymupdf.open(destino) as pdf:
                self.assertEqual(len(pdf), 4)
                texto_p2 = pdf[1].get_text()
                self.assertIn("Retirada e devolução", texto_p2)
                self.assertIn("programada pelo cliente", texto_p2.lower())
                self.assertIn("Devolução Confirmada", pdf[3].get_text())
                self.assertIn("04 / 04", pdf[3].get_text())
                self.assertIn("BAIRRO", pdf[0].get_text().upper())
                self.assertEqual(total_paginas_relatorio(dados), len(pdf))

    def test_muitas_areas_e_finalizacoes_paginam(self):
        labels = {"Entregue": {"quantidade": 50, "percentual": 50.0}}
        labels.update({f"Categoria Ficticia {i:02d}": {"quantidade": 1, "percentual": 1.0}
                       for i in range(30)})
        dados = dados_ficticios(areas=40, finalizacoes=labels)
        with tempfile.TemporaryDirectory() as tmp:
            destino = gerar_relatorio(dados, Path(tmp) / "resultado.pdf")
            with pymupdf.open(destino) as pdf:
                self.assertEqual(len(pdf), total_paginas_relatorio(dados))
                self.assertIn("Categoria Ficticia 29", "\n".join(p.get_text() for p in pdf))
                self.assertIn("BAIRRO FICTICIO 39", "\n".join(p.get_text() for p in pdf).upper())
                self.assertIn(f"{len(pdf):02d} / {len(pdf):02d}", pdf[-1].get_text())


if __name__ == "__main__":
    unittest.main()
