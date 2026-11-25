"""Testes de recuperação controlada do histórico, apenas com dados fictícios."""

import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from src.backup_historico import BackupHistorico
from src.historico import Historico, _json_canonico
from src.recuperar_historico import (
    ConflitoRecuperacao,
    ErroRecuperacao,
    RecuperacaoHistorico,
)


def dados_ficticios(pedidos=2):
    """Prepara uma competência mensal coerente, sem dados corporativos."""
    return {
        "cliente": "CLIENTE FICTICIO - TESTE RECUPERACAO",
        "periodo": "01/09/2026 a 30/09/2026",
        "pedidos": pedidos,
        "areas": [{"nome": "AREA FICTICIA", "quantidade": pedidos}],
        "horarios": [
            {"hora": f"{hora:02d}:00", "quantidade": pedidos if hora == 10 else 0}
            for hora in range(6, 24)
        ],
        "finalizacoes": {
            "Entregue": {"quantidade": pedidos, "percentual": 100.0},
        },
        "tempos_gerais": {"espera": "99:99"},
    }


class TestRecuperacaoHistorico(unittest.TestCase):
    def setUp(self):
        temporario = tempfile.TemporaryDirectory()
        self.addCleanup(temporario.cleanup)
        raiz = Path(temporario.name)
        self.pasta_principal = raiz / "principal"
        self.pasta_backups = raiz / "backups"
        self.pasta_principal.mkdir()
        self.pasta_backups.mkdir()

        self.dados = dados_ficticios()
        self.cliente = self.dados["cliente"]
        self.competencia = "2026-09"
        self.historico = Historico(self.pasta_principal)
        self.backup = BackupHistorico(self.pasta_principal, self.pasta_backups)
        self.recuperacao = RecuperacaoHistorico(self.pasta_principal, self.pasta_backups)
        _, self.registro = self.historico.registrar(self.dados)
        _, self.copia = self.backup.criar(self.cliente, self.competencia)

    def test_inspecionar_nao_modifica_registro_nem_backup(self):
        principal_antes = self.registro.read_bytes()
        backup_antes = self.copia.read_bytes()
        situacao = self.recuperacao.inspecionar(self.cliente, self.competencia, self.copia)
        self.assertEqual(situacao, "existente")
        self.assertEqual(self.registro.read_bytes(), principal_antes)
        self.assertEqual(self.copia.read_bytes(), backup_antes)
        self.assertFalse((self.registro.parent / "_quarentena").exists())

    def test_registro_ausente_e_restaurado(self):
        original = self.copia.read_bytes()
        self.registro.unlink()
        self.assertEqual(
            self.recuperacao.inspecionar(self.cliente, self.competencia, self.copia),
            "ausente",
        )
        situacao, destino, quarentena = self.recuperacao.restaurar(
            self.cliente, self.competencia, self.copia,
        )
        self.assertEqual(situacao, "restaurado")
        self.assertEqual(destino, self.registro)
        self.assertIsNone(quarentena)
        self.assertEqual(destino.read_bytes(), original)
        self.assertEqual(self.copia.read_bytes(), original)

    def test_registro_valido_igual_nao_e_substituido(self):
        original = self.registro.read_bytes()
        situacao, destino, quarentena = self.recuperacao.restaurar(
            self.cliente, self.competencia, self.copia,
            autorizar_isolamento=True,
        )
        self.assertEqual(situacao, "existente")
        self.assertEqual(destino, self.registro)
        self.assertIsNone(quarentena)
        self.assertEqual(self.registro.read_bytes(), original)

    def test_registro_valido_diferente_e_protegido(self):
        self.registro.unlink()
        self.historico.registrar(dados_ficticios(pedidos=5))
        original = self.registro.read_bytes()
        self.assertEqual(
            self.recuperacao.inspecionar(self.cliente, self.competencia, self.copia),
            "conflito",
        )
        with self.assertRaises(ConflitoRecuperacao):
            self.recuperacao.restaurar(
                self.cliente, self.competencia, self.copia,
                autorizar_isolamento=True,
            )
        self.assertEqual(self.registro.read_bytes(), original)

    def test_corrompido_sem_autorizacao_e_preservado(self):
        self.registro.write_text("{json corrompido", encoding="utf-8")
        self.assertEqual(
            self.recuperacao.inspecionar(self.cliente, self.competencia, self.copia),
            "corrompido",
        )
        with self.assertRaises(ErroRecuperacao):
            self.recuperacao.restaurar(self.cliente, self.competencia, self.copia)
        self.assertEqual(self.registro.read_text(encoding="utf-8"), "{json corrompido")
        self.assertFalse((self.registro.parent / "_quarentena").exists())

    def test_corrompido_autorizado_vai_para_quarentena(self):
        danificado = b"{json corrompido"
        self.registro.write_bytes(danificado)
        situacao, destino, isolado = self.recuperacao.restaurar(
            self.cliente, self.competencia, self.copia,
            autorizar_isolamento=True,
        )
        self.assertEqual(situacao, "restaurado_apos_isolamento")
        self.assertEqual(destino, self.registro)
        self.assertIsNotNone(isolado)
        self.assertEqual(isolado.parent.name, "_quarentena")
        self.assertEqual(isolado.read_bytes(), danificado)
        self.assertEqual(destino.read_bytes(), self.copia.read_bytes())

    def test_copia_corrompida_nao_e_utilizada(self):
        original = self.registro.read_bytes()
        self.copia.write_text("arquivo danificado", encoding="utf-8")
        with self.assertRaises(ErroRecuperacao):
            self.recuperacao.restaurar(self.cliente, self.competencia, self.copia)
        self.assertEqual(self.registro.read_bytes(), original)

    def test_copia_de_outra_operacao_e_recusada(self):
        with self.assertRaises(ErroRecuperacao):
            self.recuperacao.inspecionar("OUTRA OPERACAO", self.competencia, self.copia)

    def test_competencia_invalida_e_recusada(self):
        with self.assertRaises(ErroRecuperacao):
            self.recuperacao.inspecionar(self.cliente, "2026-13", self.copia)

    def test_bloqueio_existente_impede_recuperacao(self):
        self.registro.unlink()
        bloqueio = self.registro.parent / ".2026-09.lock"
        bloqueio.mkdir()
        with self.assertRaises(ErroRecuperacao):
            self.recuperacao.restaurar(self.cliente, self.competencia, self.copia)
        self.assertFalse(self.registro.exists())
        self.assertTrue(bloqueio.is_dir())
        bloqueio.rmdir()

    def test_pasta_principal_indisponivel_nao_e_recriada(self):
        shutil.rmtree(self.pasta_principal)
        with self.assertRaises(ErroRecuperacao):
            self.recuperacao.restaurar(self.cliente, self.competencia, self.copia)
        self.assertFalse(self.pasta_principal.exists())

    def test_recuperacao_nao_reintroduz_tempos_operacionais(self):
        self.registro.unlink()
        self.recuperacao.restaurar(self.cliente, self.competencia, self.copia)
        texto = self.registro.read_text(encoding="utf-8")
        self.assertNotIn('"tempos_gerais"', texto)
        self.assertNotIn('"espera"', texto)
        self.assertNotIn('"roteirizacao"', texto)

    def test_checksum_recalculado_nao_basta_se_dados_forem_incoerentes(self):
        """Mesmo com hashes coerentes, rejeitar totais sem consistência."""
        registro = json.loads(self.copia.read_text(encoding="utf-8"))
        adulterado = copy.deepcopy(registro)
        adulterado["dados"]["pedidos"] = 99  # Áreas/horários continuam somando 2.
        payload = adulterado["dados"]
        adulterado["sha256"] = hashlib.sha256(
            _json_canonico(payload).encode("utf-8")
        ).hexdigest()
        conteudo = (json.dumps(adulterado, ensure_ascii=False) + "\n").encode("utf-8")
        nome = f"{self.competencia}-{hashlib.sha256(conteudo).hexdigest()}.json"
        copia_incoerente = self.copia.parent / nome
        copia_incoerente.write_bytes(conteudo)

        antes = self.registro.read_bytes()
        with self.assertRaises(ErroRecuperacao):
            self.recuperacao.restaurar(
                self.cliente, self.competencia, copia_incoerente,
            )
        self.assertEqual(self.registro.read_bytes(), antes)


if __name__ == "__main__":
    unittest.main()