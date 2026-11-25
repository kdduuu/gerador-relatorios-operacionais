"""Testes de backup do histórico, sem rede e com dados inteiramente fictícios."""

import tempfile
import unittest
from pathlib import Path

from src.backup_historico import BackupHistorico, ErroBackup
from src.historico import Historico


def dados_ficticios():
    """Registro mínimo compatível com a estrutura validada pelo histórico."""
    return {
        "cliente": "CLIENTE FICTICIO - TESTE BACKUP",
        "periodo": "01/09/2026 a 30/09/2026",
        "pedidos": 3,
        "areas": [
            {"nome": "AREA ALFA", "quantidade": 2, "espera": "00:20"},
            {"nome": "AREA BETA", "quantidade": 1, "rota": "00:10"},
        ],
        "horarios": [
            {"hora": f"{hora:02d}:00", "quantidade": 3 if hora == 10 else 0}
            for hora in range(6, 24)
        ],
        "finalizacoes": {"Entregue": {"quantidade": 2, "percentual": 66.67}},
        "tempos_gerais": {"espera": "00:22"},
    }


class TestBackupHistorico(unittest.TestCase):
    def setUp(self):
        temporario = tempfile.TemporaryDirectory()
        self.addCleanup(temporario.cleanup)
        raiz = Path(temporario.name)
        self.pasta_historico = raiz / "historico_principal"
        self.pasta_backup = raiz / "backups_separados"
        self.pasta_historico.mkdir()
        self.pasta_backup.mkdir()
        self.dados = dados_ficticios()
        self.historico = Historico(self.pasta_historico)
        self.backup = BackupHistorico(self.pasta_historico, self.pasta_backup)
        self.cliente = self.dados["cliente"]
        self.competencia = "2026-09"

    def test_criar_verificar_e_nao_incluir_tempos(self):
        self.historico.registrar(self.dados)
        situacao, arquivo = self.backup.criar(self.cliente, self.competencia)
        self.assertEqual(situacao, "criado")
        self.assertTrue(arquivo.is_file())
        self.assertTrue(self.backup.verificar(self.cliente, self.competencia, arquivo))
        conteudo = arquivo.read_text(encoding="utf-8")
        self.assertNotIn('"tempos_gerais"', conteudo)
        self.assertNotIn('"espera"', conteudo)
        self.assertNotIn('"rota"', conteudo)

    def test_repetir_backup_nao_sobrescreve(self):
        self.historico.registrar(self.dados)
        _, original = self.backup.criar(self.cliente, self.competencia)
        bytes_antes = original.read_bytes()
        situacao, repetido = self.backup.criar(self.cliente, self.competencia)
        self.assertEqual(situacao, "existente")
        self.assertEqual(original, repetido)
        self.assertEqual(bytes_antes, repetido.read_bytes())

    def test_backup_corrompido_rejeitado_inclusive_na_repeticao(self):
        self.historico.registrar(self.dados)
        _, arquivo = self.backup.criar(self.cliente, self.competencia)
        arquivo.write_text("conteudo invalido", encoding="utf-8")
        with self.assertRaises(ErroBackup):
            self.backup.verificar(self.cliente, self.competencia, arquivo)
        with self.assertRaises(ErroBackup):
            self.backup.criar(self.cliente, self.competencia)
        self.assertEqual(arquivo.read_text(encoding="utf-8"), "conteudo invalido")

    def test_origem_corrompida_impede_backup(self):
        _, origem = self.historico.registrar(self.dados)
        origem.write_text("{json incompleto", encoding="utf-8")
        with self.assertRaises(ErroBackup):
            self.backup.criar(self.cliente, self.competencia)

    def test_competencia_ausente_ou_invalida(self):
        with self.assertRaises(ErroBackup):
            self.backup.criar(self.cliente, self.competencia)
        with self.assertRaises(ErroBackup):
            self.backup.criar(self.cliente, "2026-13")

    def test_origem_e_destino_nao_podem_coincidir_ou_ser_aninhados(self):
        with self.assertRaises(ErroBackup):
            BackupHistorico(self.pasta_historico, self.pasta_historico)
        pasta_interna = self.pasta_historico / "backups"
        pasta_interna.mkdir()
        with self.assertRaises(ErroBackup):
            BackupHistorico(self.pasta_historico, pasta_interna)
        pasta_inversa = self.pasta_backup / "historico"
        pasta_inversa.mkdir()
        with self.assertRaises(ErroBackup):
            BackupHistorico(pasta_inversa, self.pasta_backup)

    def test_destino_inacessivel_nao_e_recriado(self):
        self.historico.registrar(self.dados)
        self.pasta_backup.rmdir()
        with self.assertRaises(ErroBackup):
            self.backup.criar(self.cliente, self.competencia)
        self.assertFalse(self.pasta_backup.exists())

    def test_copia_nao_pode_ser_verificada_com_outro_cliente(self):
        self.historico.registrar(self.dados)
        _, arquivo = self.backup.criar(self.cliente, self.competencia)
        with self.assertRaises(ErroBackup):
            self.backup.verificar("OUTRA OPERACAO", self.competencia, arquivo)

    def test_bloqueio_existente_impede_nova_copia(self):
        self.historico.registrar(self.dados)
        _, arquivo = self.backup.criar(self.cliente, self.competencia)
        original = arquivo.read_bytes()
        bloqueio = self.backup._pasta_competencia(self.cliente) / ".2026-09.backup.lock"
        bloqueio.mkdir()
        with self.assertRaises(ErroBackup):
            self.backup.criar(self.cliente, self.competencia)
        self.assertEqual(arquivo.read_bytes(), original)
        bloqueio.rmdir()


if __name__ == "__main__":
    unittest.main()