import tempfile
import unittest
from pathlib import Path

import pymupdf

from src.gerar_relatorio import gerar_relatorio


class TestPDF(unittest.TestCase):
    def test_pdf_com_cliente_e_medidas_ficticias(self):
        dados = {
            "cliente": "CLIENTE FICTICIO - ROTA B",
            "periodo": "01/03/2026 a 31/03/2026",
            "pedidos": 10,
            "areas": [
                {"nome": "AREA BETA", "quantidade": 7, "separacao": "00:03", "roteirizacao": "00:18", "rota": "00:14", "espera": "00:39"},
                {"nome": "AREA ALFA", "quantidade": 3, "separacao": "00:01", "roteirizacao": "00:20", "rota": "00:12", "espera": "00:35"},
            ],
            "finalizacoes": {"Entregue": {"quantidade": 8, "percentual": 80.0}},
            "tempos_gerais": {"separacao": "00:02", "rota": "00:13", "espera": "00:38"},
            "horarios": [{"hora": f"{h:02d}:00", "quantidade": 6 if h == 15 else (4 if h == 10 else 0)} for h in range(6,24)],
            "avisos": ["Coleta incompleta"],
        }
        with tempfile.TemporaryDirectory() as pasta:
            destino = gerar_relatorio(dados, Path(pasta)/"gerado.pdf")
            with pymupdf.open(destino) as doc:
                self.assertEqual(len(doc),2)
                texto = "\n".join(p.get_text() for p in doc)
                self.assertIn("CLIENTE FICTICIO", texto)
                self.assertIn("Area Beta", texto)
                self.assertIn("10", texto)
                self.assertIn("15:00", texto)


    def test_varias_areas_nao_sao_descartadas(self):
        dados = {
            "cliente": "OPERACAO FICTICIA MULTIAREAS",
            "periodo": "01/04/2026 a 30/04/2026",
            "pedidos": 45,
            "areas": [
                {"nome": f"CIDADE TESTE {i}", "quantidade": i,
                 "separacao": "00:01", "roteirizacao": "00:03",
                 "rota": "00:06", "espera": "00:11"}
                for i in range(10)
            ],
            "finalizacoes": {"Entregue": {"quantidade": 40, "percentual": 89}},
            "tempos_gerais": {"separacao": "00:01", "rota": "00:06", "espera": "00:11"},
            "horarios": [{"hora": f"{h:02d}:00", "quantidade": 45 if h == 9 else 0}
                         for h in range(6, 24)],
            "avisos": [],
            "cadastro": None,
        }
        with tempfile.TemporaryDirectory() as pasta:
            destino = gerar_relatorio(dados, Path(pasta)/"multiareas.pdf")
            with pymupdf.open(destino) as doc:
                self.assertEqual(len(doc), 3)
                texto = "\n".join(p.get_text() for p in doc)
                self.assertIn("Cidade Teste 9", texto)
                self.assertIn("Outras 4 áreas", texto)


if __name__ == "__main__":
    unittest.main()