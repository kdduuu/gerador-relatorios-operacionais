"""Testes do comparativo mensal: somente operações e valores fictícios."""

import copy
import tempfile
import unittest

from src.comparativo import ErroComparativo, calcular_comparativo
from src.historico import Historico


def dados_ficticios(competencia="09/2026", pedidos=10, cliente="CLIENTE FICTICIO - ITAPEVI"):
    mes, ano = map(int, competencia.split("/"))
    from calendar import monthrange
    ultimo = monthrange(ano, mes)[1]
    return {
        "cliente": cliente,
        "periodo": f"01/{mes:02d}/{ano} a {ultimo:02d}/{mes:02d}/{ano}",
        "pedidos": pedidos,
        "areas": [
            {"nome": "SAO PAULO", "quantidade": pedidos * 6 // 10},
            {"nome": "COTIA", "quantidade": pedidos - pedidos * 6 // 10},
        ],
        "horarios": [
            {"hora": f"{h:02d}:00", "quantidade": pedidos if h == 10 else 0}
            for h in range(6, 24)
        ],
        "finalizacoes": {
            "Entregue": {"quantidade": pedidos // 2, "percentual": 70.0},
            "Cancelado": {"quantidade": 1, "percentual": 1.0},
        },
        "tempos_gerais": {"espera": "00:40"},
    }


class TestComparativo(unittest.TestCase):
    def setUp(self):
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        self.historico = Historico(pasta.name)
        self.agosto = dados_ficticios("08/2026", 10)
        self.setembro = dados_ficticios("09/2026", 20)
        self.historico.registrar(self.agosto)
        self.anterior = self.historico.mes_anterior(self.setembro)

    def test_pedidos_areas_entregas_e_percentuais(self):
        resultado = calcular_comparativo(self.setembro, self.anterior)
        self.assertEqual((resultado["competencia_anterior"], resultado["competencia_atual"]), ("2026-08", "2026-09"))
        self.assertEqual(resultado["pedidos"], {
            "anterior": 10, "atual": 20, "diferenca": 10, "variacao_percentual": 100.0,
        })
        self.assertEqual(resultado["entregas_registradas"]["diferenca"], 5)
        self.assertEqual(resultado["areas_atendidas"]["diferenca"], 0)
        self.assertEqual(resultado["pico_atual"]["hora"], "10:00")
        self.assertEqual(len(resultado["horarios"]), 18)

    def test_sem_mes_anterior_sem_comparativo(self):
        self.assertIsNone(calcular_comparativo(self.setembro, None))

    def test_operacao_diferente_rejeitada(self):
        outra = dados_ficticios("09/2026", 20, "OUTRA OPERACAO")
        with self.assertRaises(ErroComparativo):
            calcular_comparativo(outra, self.anterior)

    def test_pulos_de_mes_e_mes_invertido_rejeitados(self):
        for competencia in ("10/2026", "07/2026"):
            with self.subTest(competencia=competencia):
                with self.assertRaises(ErroComparativo):
                    calcular_comparativo(dados_ficticios(competencia, 20), self.anterior)

    def test_virada_de_ano(self):
        dezembro = dados_ficticios("12/2026", 10)
        janeiro = dados_ficticios("01/2027", 20)
        self.historico.registrar(dezembro)
        registro = self.historico.mes_anterior(janeiro)
        self.assertEqual(calcular_comparativo(janeiro, registro)["competencia_anterior"], "2026-12")

    def test_base_zero_nao_inventa_variacao_percentual(self):
        zero = dados_ficticios("08/2026", 0)
        # O mês de base zero precisa ser armazenado em outra pasta temporária.
        with tempfile.TemporaryDirectory() as temp:
            hist = Historico(temp)
            hist.registrar(zero)
            registro = hist.mes_anterior(self.setembro)
            resultado = calcular_comparativo(self.setembro, registro)
        self.assertIsNone(resultado["pedidos"]["variacao_percentual"])
        self.assertEqual(resultado["pedidos"]["diferenca"], 20)
        self.assertIsNone(resultado["top2_areas"]["anterior_pct"])

    def test_area_nao_listada_em_um_mes_equivale_a_zero_registros(self):
        setembro = copy.deepcopy(self.setembro)
        setembro["areas"] = [{"nome": "ITAPEVI", "quantidade": 20}]
        resultado = calcular_comparativo(setembro, self.anterior)
        por_nome = {a["nome"]: a for a in resultado["areas"]}
        self.assertEqual(por_nome["ITAPEVI"]["anterior"], 0)
        self.assertEqual(por_nome["ITAPEVI"]["atual"], 20)
        self.assertEqual(por_nome["SAO PAULO"]["atual"], 0)

    def test_nome_com_e_sem_acento_identifica_mesma_area(self):
        setembro = copy.deepcopy(self.setembro)
        setembro["areas"][0]["nome"] = "SÃO PAULO"
        resultado = calcular_comparativo(setembro, self.anterior)
        self.assertEqual(len(resultado["areas"]), 2)
        self.assertEqual(resultado["areas"][0]["nome"], "SÃO PAULO")

    def test_categorias_ausentes_nao_sao_zero(self):
        setembro = copy.deepcopy(self.setembro)
        del setembro["finalizacoes"]["Cancelado"]
        resultado = calcular_comparativo(setembro, self.anterior)
        cancelado = next(item for item in resultado["finalizacoes"] if item["nome"] == "Cancelado")
        self.assertIsNone(cancelado["atual"])
        self.assertIsNone(cancelado["diferenca"])
        self.assertFalse(cancelado["comparavel"])

    def test_dados_atual_e_historico_nao_sao_alterados(self):
        antes_atual = copy.deepcopy(self.setembro)
        antes_anterior = copy.deepcopy(self.anterior)
        calcular_comparativo(self.setembro, self.anterior)
        self.assertEqual(self.setembro, antes_atual)
        self.assertEqual(self.anterior, antes_anterior)

    def test_metadados_anterior_adulterados_rejeitados(self):
        adulterado = copy.deepcopy(self.anterior)
        adulterado["competencia"] = "2026-07"
        with self.assertRaises(ErroComparativo):
            calcular_comparativo(self.setembro, adulterado)

    def test_duplicidade_areas_normalizadas_rejeitada(self):
        setembro = copy.deepcopy(self.setembro)
        setembro["areas"] = [
            {"nome": "SAO PAULO", "quantidade": 10},
            {"nome": "SÃO PAULO", "quantidade": 10},
        ]
        with self.assertRaises(ErroComparativo):
            calcular_comparativo(setembro, self.anterior)

    def test_horas_ausentes_rejeitadas(self):
        setembro = copy.deepcopy(self.setembro)
        setembro["horarios"][0]["quantidade"] = 0
        setembro["horarios"].pop(0)
        with self.assertRaises(ErroComparativo):
            calcular_comparativo(setembro, self.anterior)


if __name__ == "__main__":
    unittest.main()
