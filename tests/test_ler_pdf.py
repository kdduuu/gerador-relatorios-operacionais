
import unittest
from unittest.mock import patch

from src.ler_pdf import processar_pdf

# Dados fictícios para os testes
PAGINA_1 = """01/09/2026 a 30/09/2026
Área
Quantidades
Separação
Roteirização
Rota
Espera total cliente
CIDADE TESTE
3
00:01
00:27
00:15
00:44
Separação: 00:01 ; Rota: 00:15; Espera do cliente: 00:44
"""

PAGINA_2 = """Finalizações
Entregue (2 - 66,67%)
COLETA REALIZADA (1...
Número de pedidos (3)
"""


class TestExtrator(unittest.TestCase):

    def test_extracao_correta(self):
        with patch(
            "src.ler_pdf.ler_paginas",
            return_value=(PAGINA_1, PAGINA_2)
        ):
            resultado = processar_pdf("teste.pdf")

        self.assertEqual(resultado["pedidos"], 3)
        self.assertEqual(resultado["areas"][0]["quantidade"], 3)
        self.assertEqual(
            resultado["finalizacoes"]["Entregue"]["quantidade"],
            2
        )

    def test_divergencia_de_pedidos(self):
        pagina_incorreta = PAGINA_2.replace(
            "Número de pedidos (3)",
            "Número de pedidos (4)"
        )

        with patch(
            "src.ler_pdf.ler_paginas",
            return_value=(PAGINA_1, pagina_incorreta)
        ), self.assertRaisesRegex(ValueError, "Divergência"):
            processar_pdf("teste.pdf")

    def test_legenda_incompleta(self):
        with patch(
            "src.ler_pdf.ler_paginas",
            return_value=(PAGINA_1, PAGINA_2)
        ):
            resultado = processar_pdf("teste.pdf")

        self.assertNotIn(
            "COLETA REALIZADA",
            resultado["finalizacoes"]
        )
        self.assertTrue(
            any("COLETA REALIZADA" in aviso
                for aviso in resultado["avisos"])
        )


if __name__ == "__main__":
    unittest.main()
