"""Testes de integração local: PDF + histórico + comparativo + backup.

Não utilizam dados corporativos, pastas de rede ou PDFs originais reais.
"""

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf

from src.backup_historico import BackupHistorico, ErroBackup
from src.fluxo_operacional import executar_fluxo, inspecionar_fluxo
from src.historico import ConflitoHistorico, ErroHistorico, Historico


def dados_ficticios(mes=9, pedidos=10):
    ultimo = {8: 31, 9: 30, 10: 31}[mes]
    return {
        "cliente": "OPERACAO FICTICIA - TESTE INTEGRADO",
        "periodo": f"01/{mes:02d}/2026 a {ultimo:02d}/{mes:02d}/2026",
        "pedidos": pedidos,
        "areas": [
            {"nome": "CIDADE ALFA", "quantidade": pedidos // 2},
            {"nome": "CIDADE BETA", "quantidade": pedidos - pedidos // 2},
        ],
        "horarios": [
            {"hora": f"{h:02d}:00", "quantidade": pedidos if h == 10 else 0}
            for h in range(6, 24)
        ],
        "finalizacoes": {"Entregue": {"quantidade": pedidos // 2, "percentual": 70.0}},
        "avisos": [],
    }


class TestFluxoOperacional(unittest.TestCase):
    def setUp(self):
        temporario = tempfile.TemporaryDirectory()
        self.addCleanup(temporario.cleanup)
        self.raiz = Path(temporario.name)
        self.hist = self.raiz / "hist"
        self.backup = self.raiz / "back"
        self.saida = self.raiz / "saida"
        self.hist.mkdir()
        self.backup.mkdir()
        self.saida.mkdir()
        self.dados = dados_ficticios()

    def executar(self, nome="gerado.pdf", dados=None, **kwargs):
        return executar_fluxo(
            dados or self.dados, self.saida / nome, self.hist, self.backup, **kwargs,
        )

    def test_sem_mes_anterior_gera_duas_paginas_e_backup(self):
        r = self.executar()
        self.assertEqual((r.estado, r.historico, r.backup), ("concluido", "criado", "criado"))
        self.assertIsNone(r.mes_anterior)
        with pymupdf.open(r.destino_pdf) as pdf:
            self.assertEqual(len(pdf), 2)
        self.assertIsNotNone(Historico(self.hist).consultar(self.dados["cliente"], "2026-09"))

    def test_com_mes_anterior_gera_tres_paginas(self):
        Historico(self.hist).registrar(dados_ficticios(8, 8))
        r = self.executar()
        self.assertEqual(r.mes_anterior, "2026-08")
        with pymupdf.open(r.destino_pdf) as pdf:
            self.assertEqual(len(pdf), 3)
            self.assertIn("COMPARATIVO MENSAL", pdf[2].get_text())

    def test_repetir_mes_em_outro_nome_reconhece_registro_e_backup(self):
        self.executar()
        r = self.executar("segundo.pdf")
        self.assertEqual((r.historico, r.backup), ("existente", "existente"))

    def test_previa_nao_grava_arquivos(self):
        plano = inspecionar_fluxo(self.dados, self.hist, self.backup)
        self.assertEqual(plano.registro_atual, "novo")
        self.assertIsNone(plano.mes_anterior)
        self.assertEqual(list(self.hist.iterdir()), [])
        self.assertEqual(list(self.backup.iterdir()), [])

    def test_previa_detecta_mes_anterior(self):
        Historico(self.hist).registrar(dados_ficticios(8, 6))
        plano = inspecionar_fluxo(self.dados, self.hist, self.backup)
        self.assertEqual(plano.mes_anterior, "2026-08")
        self.assertIsNotNone(plano.comparativo)

    def test_conflito_bloqueia_antes_de_criar_pdf(self):
        Historico(self.hist).registrar(self.dados)
        corrigido = copy.deepcopy(self.dados)
        corrigido["areas"][0]["quantidade"] -= 1
        corrigido["areas"][1]["quantidade"] += 1
        with self.assertRaises(ConflitoHistorico):
            self.executar(dados=corrigido)
        self.assertFalse((self.saida / "gerado.pdf").exists())

    def test_historico_indisponivel_bloqueia_antes_do_pdf(self):
        self.hist.rmdir()
        with self.assertRaises(ErroHistorico):
            self.executar()
        self.assertFalse((self.saida / "gerado.pdf").exists())

    def test_backup_indisponivel_bloqueia_antes_do_pdf(self):
        self.backup.rmdir()
        with self.assertRaises(ErroBackup):
            self.executar()
        self.assertFalse((self.saida / "gerado.pdf").exists())

    def test_mes_anterior_corrompido_nao_e_tratado_como_ausente(self):
        _, caminho = Historico(self.hist).registrar(dados_ficticios(8))
        caminho.write_text("{arquivo incompleto", encoding="utf-8")
        with self.assertRaises(ErroHistorico):
            self.executar()
        self.assertFalse((self.saida / "gerado.pdf").exists())

    def test_falha_no_registro_apos_pdf_e_parcial(self):
        with patch.object(Historico, "registrar", side_effect=ErroHistorico("rede desconectada")):
            r = self.executar()
        self.assertEqual((r.estado, r.historico, r.backup), ("parcial", "falhou", "nao_executado"))
        self.assertIn("rede desconectada", r.detalhe)
        self.assertTrue(r.destino_pdf.is_file())

    def test_falha_no_backup_apos_pdf_e_parcial(self):
        with patch.object(BackupHistorico, "criar", side_effect=ErroBackup("backup offline")):
            r = self.executar()
        self.assertEqual((r.estado, r.historico, r.backup), ("parcial", "criado", "falhou"))
        self.assertIn("backup offline", r.detalhe)
        self.assertTrue(r.destino_pdf.is_file())
        self.assertIsNotNone(Historico(self.hist).consultar(self.dados["cliente"], "2026-09"))

    def test_pdf_preexistente_nao_e_substituido_sem_permissao(self):
        destino = self.saida / "gerado.pdf"
        destino.write_bytes(b"CONTEUDO ANTERIOR")
        with self.assertRaises(FileExistsError):
            self.executar()
        self.assertEqual(destino.read_bytes(), b"CONTEUDO ANTERIOR")
        self.assertIsNone(Historico(self.hist).consultar(self.dados["cliente"], "2026-09"))

    def test_pdf_preexistente_pode_ser_substituido_com_permissao(self):
        destino = self.saida / "gerado.pdf"
        destino.write_bytes(b"CONTEUDO ANTERIOR")
        r = self.executar(autorizar_substituicao_pdf=True)
        self.assertEqual(r.estado, "concluido")
        self.assertTrue(destino.read_bytes().startswith(b"%PDF-"))

    def test_pdf_de_origem_nao_pode_ser_destino(self):
        caminho = self.saida / "gerado.pdf"
        caminho.write_bytes(b"PDF DE ORIGEM")
        with self.assertRaises(ValueError):
            self.executar(origem_pdf=caminho, autorizar_substituicao_pdf=True)
        self.assertEqual(caminho.read_bytes(), b"PDF DE ORIGEM")

    def test_falha_na_geracao_nao_registra_historico(self):
        with patch("src.fluxo_operacional.gerar_relatorio", side_effect=OSError("falha do gerador")):  # noqa: SIM117
            with self.assertRaises(OSError):
                self.executar()
        self.assertFalse((self.saida / "gerado.pdf").exists())
        self.assertIsNone(Historico(self.hist).consultar(self.dados["cliente"], "2026-09"))


if __name__ == "__main__":
    unittest.main()
