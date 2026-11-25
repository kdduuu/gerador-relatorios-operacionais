"""Coordena PDF, histórico compartilhado e backup, sem dependência da interface.

A consulta do histórico é obrigatória para a geração *integrada*; indisponibilidade
não é interpretada como ausência de mês anterior. Nenhum caminho corporativo é fixo.

Ordem: validar -> consultar -> comparar -> salvar PDF -> registrar -> criar backup.
Se uma operação posterior ao salvamento falhar, retorna conclusão PARCIAL.
"""

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from src.backup_historico import BackupHistorico
from src.comparativo import calcular_comparativo
from src.gerar_relatorio import gerar_relatorio
from src.historico import (
    ConflitoHistorico,
    Historico,
    _json_canonico,
    _resumo,
)


@dataclass(frozen=True)
class PlanoGeracao:
    """Prévia verificável, sem gravações na pasta compartilhada."""

    competencia: str
    mes_anterior: str | None
    registro_atual: str  # 'novo' ou 'existente'
    comparativo: dict | None


@dataclass(frozen=True)
class ResultadoGeracao:
    """Separa conclusão do PDF, do histórico e do backup para a interface."""

    destino_pdf: Path
    estado: str  # 'concluido' ou 'parcial'
    historico: str  # 'criado', 'existente' ou 'falhou'
    backup: str  # 'criado', 'existente', 'falhou' ou 'nao_executado'
    mes_anterior: str | None
    detalhe: str | None = None


def inspecionar_fluxo(dados, pasta_historico, pasta_backups):
    """Valida tudo que é possível antes de o operador solicitar o PDF.

    Não cria arquivos nem diretórios. Os caminhos-base devem existir previamente.
    Lê o registro atual para detectar correções/conflitos *antes* da geração.
    """
    atual = _resumo(dados)
    historico = Historico(pasta_historico)
    # A configuração de backup precisa estar válida antes de salvar o PDF.
    BackupHistorico(pasta_historico, pasta_backups)

    existente = historico.consultar(atual["operacao"], atual["competencia"])
    if existente is not None and _json_canonico(existente) != _json_canonico(atual):
        raise ConflitoHistorico(
            "Já existe um registro diferente para esta operação e competência. "
            "O PDF não foi gerado e o histórico não foi alterado."
        )

    anterior = historico.mes_anterior(dados)
    comparativo = calcular_comparativo(dados, anterior)
    return PlanoGeracao(
        competencia=atual["competencia"],
        mes_anterior=(anterior["competencia"] if anterior is not None else None),
        registro_atual=("existente" if existente is not None else "novo"),
        comparativo=comparativo,
    )


def _salvar_pdf_atomico(dados, destino, comparativo, *, substituir=False):
    """Publica um PDF completo, sem arquivo parcialmente gerado no destino.

    Sem autorização, usa criação exclusiva no destino: rename no Windows e
    hardlink no POSIX. O temporário é criado na mesma pasta do destino.
    """
    destino = Path(destino)
    if destino.suffix.lower() != ".pdf":
        raise ValueError("O arquivo de saída precisa ter extensão .pdf.")
    if not destino.parent.is_dir():
        raise FileNotFoundError("A pasta escolhida para o PDF não está disponível.")
    if destino.exists() and not substituir:
        raise FileExistsError("Já existe um PDF com esse nome. Escolha outro nome.")

    temporario = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".relatorio_", suffix=".pdf",
            dir=destino.parent, delete=False,
        ) as arquivo:
            temporario = Path(arquivo.name)
        gerar_relatorio(dados, temporario, comparativo)
        with temporario.open("rb") as saida:
            cabecalho = saida.read(5)
        if temporario.stat().st_size < 8 or cabecalho != b"%PDF-":
            raise OSError("O gerador não produziu um PDF válido.")

        if substituir:
            os.replace(temporario, destino)
        elif os.name == "nt":
            # No Windows, rename não substitui um arquivo preexistente.
            os.rename(temporario, destino)
        else:
            # No POSIX, rename substituiria: hardlink exclusiva evita isso.
            os.link(temporario, destino)
        return destino
    finally:
        if temporario is not None:
            temporario.unlink(missing_ok=True)


def executar_fluxo(
    dados,
    destino_pdf,
    pasta_historico,
    pasta_backups,
    *,
    origem_pdf=None,
    autorizar_substituicao_pdf=False,
):
    """Executa o fluxo de geração e registra separadamente seus resultados.

    Antes de salvar o PDF, falhas de validação, rede, configuração e conflito
    interrompem a execução. Depois do PDF salvo, uma falha de registro ou
    backup produz ResultadoGeracao(estado='parcial') com diagnóstico explícito.
    Nada é restaurado ou corrigido automaticamente.
    """
    destino = Path(destino_pdf)
    if origem_pdf is not None and destino.resolve() == Path(origem_pdf).resolve():
        raise ValueError("O destino não pode substituir o PDF original do AtivMob.")

    plano = inspecionar_fluxo(dados, pasta_historico, pasta_backups)
    _salvar_pdf_atomico(
        dados, destino, plano.comparativo,
        substituir=autorizar_substituicao_pdf,
    )

    try:
        status_historico, _ = Historico(pasta_historico).registrar(dados)
    except Exception as erro:  # Só depois que o PDF foi salvo.  # noqa: BLE001
        return ResultadoGeracao(
            destino, "parcial", "falhou", "nao_executado",
            plano.mes_anterior, f"Histórico pendente: {erro}",
        )

    try:
        status_backup, _ = BackupHistorico(pasta_historico, pasta_backups).criar(
            dados["cliente"], plano.competencia,
        )
    except Exception as erro:  # O histórico pode estar correto, mas sem backup.  # noqa: BLE001
        return ResultadoGeracao(
            destino, "parcial", status_historico, "falhou",
            plano.mes_anterior, f"Backup pendente: {erro}",
        )

    return ResultadoGeracao(
        destino, "concluido", status_historico, status_backup,
        plano.mes_anterior,
    )
