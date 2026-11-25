import unittest

from src.indicadores import calcular_indicadores


class TestIndicadores(unittest.TestCase):
    def test_indicadores_dependem_dos_dados(self):
        dados = {
            "pedidos": 10,
            "areas": [{"nome": "ALFA", "quantidade": 3},
                      {"nome": "BETA", "quantidade": 7}],
            "horarios": [{"hora": f"{h:02d}:00", "quantidade": 6 if h == 15 else (4 if h == 10 else 0)}
                         for h in range(6, 24)],
        }
        indicadores = calcular_indicadores(dados)
        self.assertEqual(indicadores["maior_area"]["nome"], "BETA")
        self.assertEqual(indicadores["concentracao_duas"], 100)
        self.assertEqual(indicadores["pico"]["hora"], "15:00")
        self.assertEqual(indicadores["participacao_pico"], 60)
        self.assertEqual(indicadores["pedidos_manha"], 4)

    def test_zero_pedidos_nao_divide_por_zero(self):
        dados = {"pedidos": 0, "areas": [],
                 "horarios": [{"hora": "06:00", "quantidade": 0}]}
        self.assertEqual(calcular_indicadores(dados)["concentracao_duas"], 0)


if __name__ == "__main__":
    unittest.main()