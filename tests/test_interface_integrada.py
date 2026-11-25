"""Testes da configuração local e mensagens da interface, sem abrir janela.

Usa pastas temporárias e dados sintéticos; nunca acessa a rede corporativa.
"""

import json
import tempfile
import unittest
from pathlib import Path

from src.backup_historico import ErroBackup
from src.fluxo_operacional import PlanoGeracao, ResultadoGeracao
from src.interface import (
    descricao_plano,
    descricao_resultado,
    ler_configuracao,
    salvar_configuracao,
)


class TestConfiguracaoInterface(unittest.TestCase):
    def setUp(self):
        temporario = tempfile.TemporaryDirectory()
        self.addCleanup(temporario.cleanup)
        raiz = Path(temporario.name)
        self.historico = raiz / "historico"
        self.backup = raiz / "backups"
        self.historico.mkdir()
        self.backup.mkdir()
        self.arquivo_config = raiz / "local" / "config.json"

    def test_configuracao_salva_e_lida(self):
        salvar_configuracao(self.arquivo_config, self.historico, self.backup)
        self.assertEqual(
            ler_configuracao(self.arquivo_config), (self.historico, self.backup),
        )

    def test_arquivo_config_nao_contem_outros_dados(self):
        salvar_configuracao(self.arquivo_config, self.historico, self.backup)
        conteudo = json.loads(self.arquivo_config.read_text(encoding="utf-8"))
        self.assertEqual(set(conteudo), {"versao", "historico", "backup"})

    def test_configuracao_ausente_nao_e_criada_ao_ler(self):
        self.assertIsNone(ler_configuracao(self.arquivo_config))
        self.assertFalse(self.arquivo_config.exists())

    def test_configuracao_invalida_nao_e_ativada(self):
        self.arquivo_config.parent.mkdir()
        self.arquivo_config.write_text("{json incompleto", encoding="utf-8")
        self.assertIsNone(ler_configuracao(self.arquivo_config))
        self.arquivo_config.write_text('{"versao": 9, "historico": "a", "backup": "b"}')
        self.assertIsNone(ler_configuracao(self.arquivo_config))

    def test_configuracao_recusa_mesma_pasta(self):
        with self.assertRaises(ErroBackup):
            salvar_configuracao(self.arquivo_config, self.historico, self.historico)
        self.assertFalse(self.arquivo_config.exists())

    def test_configuracao_recusa_backup_inexistente(self):
        with self.assertRaises(ErroBackup):
            salvar_configuracao(
                self.arquivo_config, self.historico, self.backup / "inexistente",
            )
        self.assertFalse(self.arquivo_config.exists())

    def test_configuracao_recusa_caminho_relativo(self):
        with self.assertRaises(ValueError):
            salvar_configuracao(self.arquivo_config, "dados/historico", self.backup)
        self.assertFalse(self.arquivo_config.exists())

    def test_previa_identifica_comparativo_sem_afirmar_geracao(self):
        plano = PlanoGeracao("2026-10", "2026-09", "novo", {"teste": True})
        texto = descricao_plano(plano)
        self.assertIn("2026-09", texto)
        self.assertIn("não cadastrado", texto)
        self.assertNotIn("gerado", texto)

    def test_previa_sem_mes_anterior(self):
        plano = PlanoGeracao("2026-09", None, "existente", None)
        texto = descricao_plano(plano)
        self.assertIn("Sem mês anterior", texto)
        self.assertIn("já cadastrado", texto)

    def test_estado_parcial_nao_e_mostrado_como_backup_concluido(self):
        resultado = ResultadoGeracao(
            Path("teste.pdf"), "parcial", "criado", "falhou", None, "Falha simulada",
        )
        texto = descricao_resultado(resultado)
        self.assertIn("Histórico: criado", texto)
        self.assertIn("Backup: falhou", texto)


if __name__ == "__main__":
    unittest.main()