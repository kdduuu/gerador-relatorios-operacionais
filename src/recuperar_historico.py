"""Recuperacao supervisionada dos JSONs mensais do historico.

Nunca substitui registro valido. Cópia deve ser indicada explicitamente.
Registro danificado so pode ser isolado com autorizacao explicita.
Nao integra a interface e nao restaura nada ao importar este modulo.
"""

import hashlib
import os
import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from src.backup_historico import BackupHistorico, ErroBackup
from src.historico import (
    ErroHistorico,
    _identificador_operacao,
    _json_canonico,
    _resumo,
)


class ErroRecuperacao(Exception):
    """Falha ou recusa segura de uma recuperacao."""


class ConflitoRecuperacao(ErroRecuperacao):
    """Ja existe registro valido e diferente da copia selecionada."""


class RecuperacaoHistorico:
    """Le e recupera uma competencia especifica, com backup validado."""

    def __init__(self, pasta_historico, pasta_backups):
        try:
            self.backup = BackupHistorico(pasta_historico, pasta_backups)
        except ErroBackup as erro:
            raise ErroRecuperacao(str(erro)) from erro
        self.historico = self.backup.historico

    @staticmethod
    def _dados_coerentes(dados):
        """Exige estrutura e totais validos, alem da assinatura SHA-256."""
        try:
            normalizado = _resumo({
                "cliente": dados["operacao"],
                "periodo": dados["periodo"],
                "pedidos": dados["pedidos"],
                "areas": dados["areas"],
                "horarios": dados["horarios"],
                "finalizacoes": dados["finalizacoes"],
            })
            return _json_canonico(normalizado) == _json_canonico(dados)
        except (ErroHistorico, KeyError, TypeError, ValueError, AttributeError):
            return False

    def _copia(self, cliente, competencia, caminho_backup):
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", str(competencia)):
            raise ErroRecuperacao("Competencia invalida (AAAA-MM).")
        arquivo = Path(caminho_backup)
        if arquivo.is_symlink():
            raise ErroRecuperacao("Atalho simbolico nao e aceito como copia de seguranca.")
        try:
            self.backup.verificar(cliente, competencia, arquivo)
            conteudo = arquivo.read_bytes()
            if arquivo.name != f"{competencia}-{hashlib.sha256(conteudo).hexdigest()}.json":
                raise ErroBackup("A copia mudou enquanto era lida.")
            dados = self.backup._validar_bytes(
                conteudo, _identificador_operacao(cliente), competencia
            )
            # Assinatura valida nao basta: totais devem estar coerentes.
            if not self._dados_coerentes(dados):
                raise ErroBackup("A copia contem campos ou totais inconsistentes.")
        except (ErroBackup, ErroHistorico, OSError, KeyError, TypeError, ValueError) as erro:
            raise ErroRecuperacao(f"Copia invalida ou indisponivel: {erro}") from erro
        return conteudo, dados

    def _situacao_destino(self, cliente, competencia, dados_backup):
        """Devolve ausente, existente, conflito ou corrompido; sem escrever."""
        destino = self.historico._arquivo(cliente, competencia)
        if not self.historico.pasta_base.is_dir():
            raise ErroRecuperacao("Pasta-base do historico indisponivel.")
        if destino.is_symlink():
            raise ErroRecuperacao("Registro e um atalho simbolico; revisao necessaria.")
        try:
            atual_bytes = destino.read_bytes()
        except FileNotFoundError:
            return "ausente"
        except OSError as erro:
            raise ErroRecuperacao("Falha ao acessar registro atual; nenhuma alteracao feita.") from erro
        try:
            atual = self.backup._validar_bytes(
                atual_bytes, _identificador_operacao(cliente), competencia
            )
        except ErroBackup:
            return "corrompido"
        if not self._dados_coerentes(atual):
            return "corrompido"
        if _json_canonico(atual) == _json_canonico(dados_backup):
            return "existente"
        return "conflito"

    def inspecionar(self, cliente, competencia, caminho_backup):
        """Confere copia e estado do destino, sem escrever ou isolar arquivos."""
        _, dados = self._copia(cliente, competencia, caminho_backup)
        return self._situacao_destino(cliente, competencia, dados)

    @staticmethod
    def _gravar_sem_substituir(destino, conteudo):
        """xb: criacao exclusiva. Nunca trunca um arquivo ja existente."""
        criado = False
        try:
            with destino.open("xb") as saida:
                criado = True
                saida.write(conteudo)
                saida.flush()
                os.fsync(saida.fileno())
        except FileExistsError as erro:
            raise ErroRecuperacao("Registro apareceu durante a recuperacao; nada foi substituido.") from erro
        except OSError as erro:
            # Se a escrita falhou depois da criacao, tentar retirar a copia
            # incompleta. Se falhar, revisao manual e obrigatoria.
            if criado:
                try:
                    destino.unlink()
                except OSError as limpeza:
                    raise ErroRecuperacao(
                        f"Falha ao gravar e ao remover registro parcial: {destino}"
                    ) from limpeza
            raise ErroRecuperacao("Falha na gravacao; backup original preservado.") from erro

    def restaurar(self, cliente, competencia, caminho_backup, *, autorizar_isolamento=False):
        """Retorna (situacao, destino, quarentena_ou_None).

        Por padrao apenas repoe registro ausente; o corrompido so e isolado
        com autorizar_isolamento=True, e nunca se sobrepoe a um valido.
        """
        conteudo, dados = self._copia(cliente, competencia, caminho_backup)
        if not self.historico.pasta_base.is_dir():
            raise ErroRecuperacao("Pasta-base indisponivel; recuperacao cancelada.")

        destino = self.historico._arquivo(cliente, competencia)
        pasta = destino.parent
        try:
            (self.historico.pasta_base / "historico").mkdir(exist_ok=True)
            pasta.mkdir(exist_ok=True)
        except OSError as erro:
            raise ErroRecuperacao("Nao foi possivel preparar a pasta do registro.") from erro
        bloqueio = pasta / f".{competencia}.lock"
        try:
            bloqueio.mkdir()
        except FileExistsError as erro:
            raise ErroRecuperacao("Competencia em uso; recuperacao nao iniciada.") from erro
        except OSError as erro:
            raise ErroRecuperacao("Nao foi possivel obter bloqueio de recuperacao.") from erro

        isolado = None
        try:
            # Revalidar apos o bloqueio: outro processo pode ter registrado
            # o mes entre a inspeção e esta operacao.
            situacao = self._situacao_destino(cliente, competencia, dados)
            if situacao == "existente":
                return "existente", destino, None
            if situacao == "conflito":
                raise ConflitoRecuperacao(
                    "Ha um registro valido diferente. Recuperacao recusada; revisao necessaria."
                )
            if situacao == "corrompido":
                if not autorizar_isolamento:
                    raise ErroRecuperacao(
                        "Registro danificado: autorizacao explicita necessaria para isolar a copia atual."
                    )
                quarentena = pasta / "_quarentena"
                try:
                    quarentena.mkdir(exist_ok=True)
                    carimbo = datetime.now().strftime("%Y%m%dT%H%M%S")
                    isolado = quarentena / (
                        f"{competencia}-danificado-{carimbo}-{uuid4().hex[:12]}.json"
                    )
                    if isolado.exists():
                        raise ErroRecuperacao("Nome de isolamento ja existe; operacao cancelada.")
                    destino.rename(isolado)
                except OSError as erro:
                    raise ErroRecuperacao("Nao foi possivel preservar o registro danificado.") from erro

            try:
                self._gravar_sem_substituir(destino, conteudo)
                conferido = self.historico.consultar(cliente, competencia)
                if _json_canonico(conferido) != _json_canonico(dados):
                    raise ErroRecuperacao("Recuperacao nao passou na validacao final.")
            except (ErroHistorico, ErroRecuperacao) as erro:
                extra = f" Registro danificado preservado em: {isolado}." if isolado else ""
                raise ErroRecuperacao(f"Recuperacao nao concluida: {erro}.{extra}") from erro
            return ("restaurado_apos_isolamento" if isolado else "restaurado"), destino, isolado
        finally:
            try:
                bloqueio.rmdir()
            except OSError as erro:
                raise ErroRecuperacao(
                    "Bloqueio de recuperacao permaneceu na pasta; equipe responsavel deve verificar."
                ) from erro