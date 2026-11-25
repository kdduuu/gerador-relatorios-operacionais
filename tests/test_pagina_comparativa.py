"""Valida a pagina comparativa sem alterar o comportamento anterior do PDF.

Todos os dados desta suite sao ficticios. Nenhuma pasta corporativa e usada.
"""

import copy
import tempfile
import unittest
from pathlib import Path

import pymupdf

from src.comparativo import calcular_comparativo
from src.gerar_relatorio import gerar_relatorio, total_paginas_relatorio
from src.historico import Historico


def dados_teste(mes, pedidos):
    return {
        "cliente": "OPERACAO FICTICIA - TESTE DE COMPARATIVO",
        "periodo": f"01/{mes:02d}/2026 a {31 if mes == 8 else 30:02d}/{mes:02d}/2026",
        "pedidos": pedidos,
        "areas": [
            {"nome": "AREA ALFA", "quantidade": pedidos * 6 // 10},
            {"nome": "AREA BETA", "quantidade": pedidos - pedidos * 6 // 10},
        ],
        "horarios": [
            {"hora": f"{h:02d}:00", "quantidade": pedidos if h == 10 else 0}
            for h in range(6, 24)
        ],
        "finalizacoes": {
            "Entregue": {"quantidade": pedidos // 2, "percentual": 77.0},
            "Cancelado": {"quantidade": 1, "percentual": 1.0},
        },
        "avisos": [],
    }


class TestPaginaComparativa(unittest.TestCase):
    def setUp(self):
        temporaria = tempfile.TemporaryDirectory()
        self.addCleanup(temporaria.cleanup)
        self.raiz = Path(temporaria.name)
        self.anterior = dados_teste(8, 10)
        self.atual = dados_teste(9, 20)
        historico = Historico(self.raiz)
        historico.registrar(self.anterior)
        self.comparativo = calcular_comparativo(
            self.atual, historico.mes_anterior(self.atual),
        )

    def test_sem_historico_mantem_duas_paginas(self):
        destino = gerar_relatorio(self.atual, self.raiz / "normal.pdf")
        with pymupdf.open(destino) as pdf:
            self.assertEqual(len(pdf), 2)
            self.assertNotIn("Comparativo mensal", " ".join(p.get_text() for p in pdf))

    def test_com_historico_adiciona_terceira_pagina(self):
        destino = gerar_relatorio(
            self.atual, self.raiz / "comparativo.pdf", self.comparativo,
        )
        with pymupdf.open(destino) as pdf:
            self.assertEqual(len(pdf), 3)
            pagina = pdf[2].get_text()
            for trecho in ("COMPARATIVO MENSAL", "Ago/2026", "Set/2026", "Area Alfa", "MOVIMENTAÇÃO POR HORÁRIO"):
                with self.subTest(trecho=trecho):
                    self.assertIn(trecho, pagina)
            self.assertNotIn("Espera", pagina)
            self.assertNotIn("Separação", pagina)

    def test_corpo_das_duas_primeiras_paginas_preservado(self):
        normal = gerar_relatorio(self.atual, self.raiz / "normal.pdf")
        com = gerar_relatorio(self.atual, self.raiz / "comparativo.pdf", self.comparativo)
        with pymupdf.open(normal) as pdf_normal, pymupdf.open(com) as pdf_com:
            for numero in range(2):
                a = pdf_normal[numero].get_text().replace(f"0{numero+1} / 02", "NUMERACAO")
                b = pdf_com[numero].get_text().replace(f"0{numero+1} / 03", "NUMERACAO")
                self.assertEqual(a, b)

    def test_anexo_geografico_vem_depois_da_terceira_pagina(self):
        atual = copy.deepcopy(self.atual)
        atual["areas"] = [
            {"nome": f"AREA {i:02d}", "quantidade": 2}
            for i in range(10)
        ]
        cmp = calcular_comparativo(atual, self._registro_anterior())
        destino = gerar_relatorio(atual, self.raiz / "muitas_areas.pdf", cmp)
        with pymupdf.open(destino) as pdf:
            self.assertEqual(len(pdf), 4)
            self.assertIn("COMPARATIVO MENSAL", pdf[2].get_text())
            self.assertIn("CONTINUAÇÃO", pdf[3].get_text().upper())
            self.assertEqual(total_paginas_relatorio(atual, cmp), 4)

    def test_comparativo_de_outra_operacao_e_recusado(self):
        errado = copy.deepcopy(self.comparativo)
        errado["operacao"] = "OPERACAO DIFERENTE"
        with self.assertRaises(ValueError):
            gerar_relatorio(self.atual, self.raiz / "invalido.pdf", errado)
        self.assertFalse((self.raiz / "invalido.pdf").exists())

    def test_meses_divergentes_sao_recusados(self):
        errado = copy.deepcopy(self.comparativo)
        errado["competencia_anterior"] = "2026-07"
        with self.assertRaises(ValueError):
            gerar_relatorio(self.atual, self.raiz / "invalido.pdf", errado)

    def test_base_anterior_zero_sem_percentual_inventado(self):
        with tempfile.TemporaryDirectory() as outra_pasta:
            antigo = dados_teste(8, 0)
            hist = Historico(outra_pasta)
            hist.registrar(antigo)
            cmp = calcular_comparativo(self.atual, hist.mes_anterior(self.atual))
            destino = gerar_relatorio(self.atual, self.raiz / "base_zero.pdf", cmp)
            with pymupdf.open(destino) as pdf:
                texto = pdf[2].get_text().lower()
                self.assertIn("base zero", texto)
                self.assertNotIn("nan", texto)
                self.assertNotIn("inf%", texto)

    def _registro_anterior(self):
        return Historico(self.raiz).mes_anterior(self.atual)


if __name__ == "__main__":
    unittest.main()
