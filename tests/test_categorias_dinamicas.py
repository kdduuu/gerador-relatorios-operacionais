"""Categorias dinâmicas do AtivMob: dados inventados, sem documentos corporativos."""

import tempfile
import unittest
from pathlib import Path

import pymupdf

from src.gerar_relatorio import gerar_relatorio, nome_legivel
from src.ler_pdf import extrair_finalizacoes


class TestCategoriasDinamicas(unittest.TestCase):
    def test_nomes_arbitrarios_nao_exigem_nova_regra(self):
        texto = (
            "Finalizações\nEntregue (12 -\n60,00%)\n"
            "Troca / Devolução (4\n- 20,00%)\n"
            "Retira na Loja (2 - 10,00%)\n"
            "Aguardando Coleta (2 -\n10,00%)\n"
            "Número de pedidos (20)\nAgendado (20 - 100,00%)\n"
        )
        finalizacoes, avisos = extrair_finalizacoes(texto)
        self.assertEqual(list(finalizacoes), [
            "Entregue", "Troca / Devolução", "Retira na Loja", "Aguardando Coleta"
        ])
        self.assertEqual(finalizacoes["Troca / Devolução"], {"quantidade": 4, "percentual": 20.0})
        self.assertNotIn("Agendado", finalizacoes)
        self.assertEqual(avisos, [])

    def test_legenda_incompleta_e_other_nao_viram_quantidade(self):
        texto = (
            "Finalizações\nEntregue (7 - 70,00%)\n"
            "COLETA\nREALIZADA (1…\nTRANSFERIR…\nOther\n70%\n"
            "Número de pedidos (10)\nManual (10 - 100,00%)\n"
        )
        finalizacoes, avisos = extrair_finalizacoes(texto)
        self.assertEqual(list(finalizacoes), ["Entregue"])
        self.assertTrue(any("COLETA REALIZADA" in aviso for aviso in avisos))
        self.assertTrue(any("TRANSFERIR" in aviso for aviso in avisos))
        self.assertTrue(any("Other" in aviso for aviso in avisos))

    def test_sem_entregue_exige_validacao_explicita(self):
        with self.assertRaisesRegex(ValueError, "Entregue"):
            extrair_finalizacoes("Finalizações\nAguardando (8 - 100,00%)\nNúmero de pedidos (8)")

    def test_nome_em_km_preserva_unidade(self):
        self.assertEqual(nome_legivel("4 km"), "4 km")
        self.assertEqual(nome_legivel("SAO PAULO"), "São Paulo")

    def test_mais_de_seis_categorias_sao_exibidas_em_pagina_extra(self):
        nomes = ["Entregue", "Pendente", "Troca", "Devolução", "Retira", "Cancelado", "Outros", "Agendado"]
        dados = {
            "cliente": "OPERACAO FICTICIA",
            "periodo": "01/05/2026 a 31/05/2026",
            "pedidos": 16,
            "areas": [{"nome": "4 km", "quantidade": 16}],
            "horarios": [
                {"hora": f"{hora:02d}:00", "quantidade": 16 if hora == 10 else 0}
                for hora in range(6, 24)
            ],
            "finalizacoes": {
                nome: {"quantidade": 2, "percentual": 12.5} for nome in nomes
            },
            "avisos": [],
        }
        with tempfile.TemporaryDirectory() as pasta:
            destino = Path(pasta) / "relatorio.pdf"
            gerar_relatorio(dados, destino)
            with pymupdf.open(destino) as documento:
                self.assertEqual(len(documento), 3)
                self.assertIn("Outros", documento[2].get_text())
                self.assertIn("Agendado", documento[2].get_text())
                self.assertIn("DISTRIBUIÇÃO POR ÁREA", documento[0].get_text())
                self.assertIn("4 km", documento[0].get_text())


if __name__ == "__main__":
    unittest.main()
