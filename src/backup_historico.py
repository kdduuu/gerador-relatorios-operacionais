"""Cópias verificáveis e sem sobrescrita dos JSONs do histórico.

O módulo integra o fluxo de geração do aplicativo, mas NÃO restaura
registros automaticamente nem substitui cópias independentes da infraestrutura.
"""

import hashlib
import json
import os
import re
from pathlib import Path

from src.historico import (
    VERSAO,
    ErroHistorico,
    Historico,
    _identificador_operacao,
    _json_canonico,
)


class ErroBackup(Exception):
    """Falha de acesso, validação ou criação de uma cópia."""


class BackupHistorico:
    """Cria e confere cópias em uma pasta separada, previamente existente."""

    def __init__(self, pasta_historico, pasta_backups):
        try:
            self.historico = Historico(pasta_historico)
        except ErroHistorico as erro:
            raise ErroBackup(str(erro)) from erro
        self.pasta_backups = Path(pasta_backups)
        if not self.pasta_backups.is_dir():
            raise ErroBackup("Pasta de backups indisponível; nenhuma cópia será criada.")
        principal = self.historico.pasta_base.resolve()
        destino = self.pasta_backups.resolve()
        if destino == principal or destino.is_relative_to(principal) or principal.is_relative_to(destino):
            raise ErroBackup("Histórico e backups precisam de pastas-base independentes.")

    @staticmethod
    def _validar_bytes(conteudo, identificador, competencia):
        try:
            registro = json.loads(conteudo.decode("utf-8"))
            dados = registro["dados"]
            assinatura = hashlib.sha256(_json_canonico(dados).encode("utf-8")).hexdigest()
            if (
                registro["sha256"] != assinatura
                or dados["identificador"] != identificador
                or dados["competencia"] != competencia
                or dados["versao"] != VERSAO
            ):
                raise ValueError("Assinatura ou identidade divergente.")
            return dados
        except (UnicodeDecodeError, ValueError, TypeError, KeyError, AttributeError) as erro:
            raise ErroBackup("Registro inválido ou incompatível; cópia não autorizada.") from erro

    def _pasta_competencia(self, cliente):
        return self.pasta_backups / "copias" / _identificador_operacao(cliente)

    def criar(self, cliente, competencia):
        """Retorna ('criado'|'existente', caminho); nunca sobrescreve outra cópia.

        Usar após o registro mensal ter sido validado. Se o servidor estiver
        inacessível ou houver conteúdo inesperado, falha de modo explícito.
        """
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", competencia):
            raise ErroBackup("Competência inválida: use AAAA-MM.")
        try:
            confirmado = self.historico.consultar(cliente, competencia)
        except ErroHistorico as erro:
            raise ErroBackup(f"Histórico indisponível/inválido: {erro}") from erro
        if confirmado is None:
            raise ErroBackup("A competência ainda não está registrada no histórico.")

        origem = self.historico._arquivo(cliente, competencia)
        try:
            conteudo = origem.read_bytes()
        except OSError as erro:
            raise ErroBackup("Não foi possível ler o registro original.") from erro
        identificador = _identificador_operacao(cliente)
        dados = self._validar_bytes(conteudo, identificador, competencia)
        if _json_canonico(dados) != _json_canonico(confirmado):
            raise ErroBackup("O histórico mudou durante a verificação; tente novamente.")

        if not self.pasta_backups.is_dir():
            raise ErroBackup("A pasta-base de backups ficou indisponível.")
        pasta = self._pasta_competencia(cliente)
        try:
            (self.pasta_backups / "copias").mkdir(exist_ok=True)
            pasta.mkdir(exist_ok=True)
        except OSError as erro:
            raise ErroBackup("Não foi possível preparar a pasta de cópias.") from erro

        # O diretório de bloqueio é exclusivo no compartilhamento e evita que
        # dois computadores leiam a mesma cópia enquanto um a está gravando.
        bloqueio = pasta / f".{competencia}.backup.lock"
        try:
            bloqueio.mkdir()
        except FileExistsError as erro:
            raise ErroBackup("Outra cópia desta competência está em andamento; tente novamente.") from erro
        except OSError as erro:
            raise ErroBackup("Não foi possível obter bloqueio na pasta de backups.") from erro

        try:
            digest = hashlib.sha256(conteudo).hexdigest()
            arquivo = pasta / f"{competencia}-{digest}.json"
            try:
                # 'xb': criar exclusivamente, sem truncar arquivos existentes.
                with arquivo.open("xb") as saida:
                    saida.write(conteudo)
                    saida.flush()
                    os.fsync(saida.fileno())
                status = "criado"
            except FileExistsError:
                status = "existente"
            except OSError as erro:
                # Um erro pode deixar um arquivo parcial. A próxima tentativa
                # será bloqueada pela verificação até um responsável analisar.
                raise ErroBackup("Falha ao gravar a cópia; pode haver arquivo parcial.") from erro

            self.verificar(cliente, competencia, arquivo)
            return status, arquivo
        finally:
            try:
                bloqueio.rmdir()
            except OSError as erro:
                raise ErroBackup("Bloqueio de backup não removido; revisão necessária.") from erro

    def verificar(self, cliente, competencia, arquivo):
        """Confere identidade, assinatura interna e SHA-256 de um arquivo esperado."""
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", competencia):
            raise ErroBackup("Competência inválida.")
        arquivo = Path(arquivo)
        pasta_esperada = self._pasta_competencia(cliente)
        if arquivo.parent.resolve() != pasta_esperada.resolve():
            raise ErroBackup("Cópia fora da pasta de backups da operação.")
        try:
            conteudo = arquivo.read_bytes()
            assinatura_arquivo = hashlib.sha256(conteudo).hexdigest()
            if arquivo.name != f"{competencia}-{assinatura_arquivo}.json":
                raise ErroBackup("A cópia foi alterada ou está incompleta.")
            self._validar_bytes(conteudo, _identificador_operacao(cliente), competencia)
        except OSError as erro:
            raise ErroBackup("Não foi possível ler a cópia de segurança.") from erro
        return True