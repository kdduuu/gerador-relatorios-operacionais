"""Testes isolados do histórico mensal OPERACIONAL (somente dados fictícios)."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from src.historico import (
    ConflitoHistorico,
    ErroHistorico,
    Historico,
    HistoricoEmUso,
)


def dados_ficticios(cliente="CLIENTE TESTE - OPERACAO A", periodo="01/09/2026 a 30/09/2026"):
    """Modelo mínimo com os mesmos campos que o extrator entrega."""
    horarios = [
        {"hora": f"{hora:02d}:00", "quantidade": 10 if hora == 10 else 0}
        for hora in range(6, 24)
    ]
    return {
        "cliente": cliente,
        "periodo": periodo,
        "pedidos": 10,
        "areas": [
            {"nome": "CIDADE ALFA", "quantidade": 7,
             "separacao": "00:02", "roteirizacao": "00:12",
             "rota": "00:15", "espera": "00:35"},
            {"nome": "CIDADE BETA", "quantidade": 3,
             "separacao": "00:03", "roteirizacao": "00:15",
             "rota": "00:18", "espera": "00:40"},
        ],
        "horarios": horarios,
        "finalizacoes": {
            "Entregue": {"quantidade": 8, "percentual": 80.0},
            "Cancelado": {"quantidade": 2, "percentual": 20.0},
        },
        "tempos_gerais": {"separacao": "00:02", "rota": "00:16", "espera": "00:37"},
        "avisos": [],
    }


class TestHistorico(unittest.TestCase):
    def setUp(self):
        self.pasta_temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta_temp.cleanup)
        self.historico = Historico(self.pasta_temp.name)
        self.dados = dados_ficticios()

    def test_registra_e_consulta_competencia(self):
        status, arquivo = self.historico.registrar(self.dados)
        self.assertEqual(status, "criado")
        self.assertTrue(arquivo.is_file())
        registro = self.historico.consultar(self.dados["cliente"], "2026-09")
        self.assertEqual(registro["pedidos"], 10)
        self.assertEqual(registro["competencia"], "2026-09")
        self.assertEqual(len(registro["areas"]), 2)

    def test_duplicidade_igual_nao_sobrescreve(self):
        _, arquivo = self.historico.registrar(self.dados)
        conteudo_original = arquivo.read_bytes()
        status, mesmo_arquivo = self.historico.registrar(copy.deepcopy(self.dados))
        self.assertEqual(status, "existente")
        self.assertEqual(mesmo_arquivo, arquivo)
        self.assertEqual(arquivo.read_bytes(), conteudo_original)

    def test_mes_existente_com_novos_dados_rejeita_conflito(self):
        _, arquivo = self.historico.registrar(self.dados)
        conteudo_original = arquivo.read_bytes()
        corrigido = copy.deepcopy(self.dados)
        corrigido["areas"][0]["quantidade"] = 6
        corrigido["areas"][1]["quantidade"] = 4
        with self.assertRaises(ConflitoHistorico):
            self.historico.registrar(corrigido)
        self.assertEqual(arquivo.read_bytes(), conteudo_original)

    def test_mes_anterior_encontrado_na_virada_do_ano(self):
        dezembro = dados_ficticios(periodo="01/12/2026 a 31/12/2026")
        janeiro = dados_ficticios(periodo="01/01/2027 a 31/01/2027")
        self.historico.registrar(dezembro)
        anterior = self.historico.mes_anterior(janeiro)
        self.assertIsNotNone(anterior)
        self.assertEqual(anterior["competencia"], "2026-12")

    def test_ausencia_de_mes_anterior_retorna_none(self):
        self.historico.registrar(self.dados)
        outubro = dados_ficticios(periodo="01/10/2026 a 31/10/2026")
        novembro = dados_ficticios(periodo="01/11/2026 a 30/11/2026")
        self.assertEqual(self.historico.mes_anterior(outubro)["competencia"], "2026-09")
        self.assertIsNone(self.historico.mes_anterior(novembro))

    def test_operacoes_diferentes_nao_se_misturam(self):
        outro = dados_ficticios(cliente="CLIENTE TESTE - OPERACAO B")
        _, caminho_a = self.historico.registrar(self.dados)
        _, caminho_b = self.historico.registrar(outro)
        self.assertNotEqual(caminho_a, caminho_b)
        self.assertEqual(self.historico.consultar(outro["cliente"], "2026-09")["operacao"], outro["cliente"])

    def test_rejeita_periodo_parcial(self):
        parcial = dados_ficticios(periodo="05/09/2026 a 30/09/2026")
        with self.assertRaises(ErroHistorico):
            self.historico.registrar(parcial)

    def test_rejeita_divergencia_entre_areas_e_pedidos(self):
        errado = copy.deepcopy(self.dados)
        errado["areas"][0]["quantidade"] = 8
        with self.assertRaises(ErroHistorico):
            self.historico.registrar(errado)

    def test_rejeita_horarios_duplicados(self):
        errado = copy.deepcopy(self.dados)
        errado["horarios"].append({"hora": "10:00", "quantidade": 0})
        with self.assertRaises(ErroHistorico):
            self.historico.registrar(errado)

    def test_arquivo_json_corrompido_nao_e_tratado_como_ausente(self):
        _, arquivo = self.historico.registrar(self.dados)
        arquivo.write_text("{json inválido", encoding="utf-8")
        with self.assertRaises(ErroHistorico):
            self.historico.consultar(self.dados["cliente"], "2026-09")

    def test_alteracao_de_conteudo_invalida_assinatura(self):
        _, arquivo = self.historico.registrar(self.dados)
        registro = json.loads(arquivo.read_text(encoding="utf-8"))
        registro["dados"]["pedidos"] = 999
        arquivo.write_text(json.dumps(registro, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(ErroHistorico):
            self.historico.consultar(self.dados["cliente"], "2026-09")

    def test_bloqueio_impede_gravacao_sem_alterar_registro(self):
        _, arquivo = self.historico.registrar(self.dados)
        original = arquivo.read_bytes()
        bloqueio = arquivo.parent / ".2026-09.lock"
        bloqueio.mkdir()
        with self.assertRaises(HistoricoEmUso):
            self.historico.registrar(self.dados)
        self.assertEqual(arquivo.read_bytes(), original)
        bloqueio.rmdir()

    def test_nao_grava_tempo_operacional_no_json(self):
        _, arquivo = self.historico.registrar(self.dados)
        texto = arquivo.read_text(encoding="utf-8")
        self.assertNotIn('"tempos_gerais"', texto)
        self.assertNotIn('"roteirizacao"', texto)
        self.assertNotIn('"espera"', texto)

    def test_pasta_indisponivel_gera_erro(self):
        inexistente = Path(self.pasta_temp.name) / "nao_existe"
        with self.assertRaises(ErroHistorico):
            Historico(inexistente)


if __name__ == "__main__":
    unittest.main()
