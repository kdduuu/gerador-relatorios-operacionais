"""Histórico mensal compartilhável do Gerador de Relatórios.

Um JSON por operação/competência. Não altera PDFs originais nem gerados.
A pasta-base é recebida por parâmetro; nenhum endereço de rede é fixo.
"""

import hashlib
import json
import os
import re
import tempfile
import unicodedata
from calendar import monthrange
from datetime import datetime, timedelta
from pathlib import Path

VERSAO = 1


class ErroHistorico(Exception):
    """Erro de validação, leitura ou armazenamento do histórico."""


class HistoricoEmUso(ErroHistorico):
    """Outro processo está registrando a mesma competência."""


class ConflitoHistorico(ErroHistorico):
    """Já existe outro conteúdo para esta operação e competência."""


def _identificador_operacao(cliente):
    """Cria uma pasta previsível, sem confiar no nome como caminho de arquivo."""
    original = " ".join(str(cliente).split()).casefold()
    if not original:
        raise ErroHistorico("O nome da operação está vazio.")
    sem_acentos = unicodedata.normalize("NFKD", original)
    nome_ascii = sem_acentos.encode("ascii", "ignore").decode("ascii")
    apelido = re.sub(r"[^a-z0-9]+", "-", nome_ascii).strip("-")[:45] or "operacao"
    sufixo = hashlib.sha256(original.encode("utf-8")).hexdigest()[:12]
    return f"{apelido}-{sufixo}"


def _competencia(periodo):
    """Garante que o período corresponda a um mês completo."""
    resultado = re.fullmatch(r"(\d{2}/\d{2}/\d{4}) a (\d{2}/\d{2}/\d{4})", str(periodo))
    if not resultado:
        raise ErroHistorico("Período inválido: formato esperado DD/MM/AAAA a DD/MM/AAAA.")
    try:
        inicio = datetime.strptime(resultado.group(1), "%d/%m/%Y").date()
        fim = datetime.strptime(resultado.group(2), "%d/%m/%Y").date()
    except ValueError as erro:
        raise ErroHistorico("O período contém uma data inexistente.") from erro
    ultimo_dia = monthrange(inicio.year, inicio.month)[1]
    if inicio.day != 1 or fim != inicio.replace(day=ultimo_dia):
        raise ErroHistorico(
            "Somente meses completos são aceitos no histórico e na geração "
            "integrada desta aplicação. Confira o período do PDF."
        )
    return inicio.strftime("%Y-%m")


def _json_canonico(dados):
    return json.dumps(dados, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _resumo(dados):
    """Seleciona apenas os campos necessários aos comparativos (sem tempos)."""
    try:
        cliente = " ".join(dados["cliente"].split())
        competencia = _competencia(dados["periodo"])
        pedidos = dados["pedidos"]
        areas = dados["areas"]
        horarios = dados["horarios"]
        finalizacoes = dados["finalizacoes"]
    except (KeyError, TypeError, AttributeError) as erro:
        raise ErroHistorico("Dados incompletos para registrar a competência.") from erro

    if not cliente or type(pedidos) is not int or pedidos < 0:
        raise ErroHistorico("Cliente ou quantidade de pedidos inválidos.")

    try:
        mapa_areas = [
            {"nome": a["nome"].strip(), "quantidade": a["quantidade"]}
            for a in areas
        ]
        mapa_horarios = [
            {"hora": h["hora"], "quantidade": h["quantidade"]}
            for h in horarios
        ]
        mapa_finalizacoes = {
            nome: {"quantidade": item["quantidade"], "percentual": item["percentual"]}
            for nome, item in finalizacoes.items()
        }
    except (KeyError, TypeError, AttributeError) as erro:
        raise ErroHistorico("Áreas, horários ou finalizações incompletos.") from erro

    if (
        any(not a["nome"] or type(a["quantidade"]) is not int or a["quantidade"] < 0 for a in mapa_areas)
        or sum(a["quantidade"] for a in mapa_areas) != pedidos
    ):
        raise ErroHistorico("A soma das áreas não confere com os pedidos.")
    if (
        any(not re.fullmatch(r"\d{2}:00", str(h["hora"]))
            or type(h["quantidade"]) is not int or h["quantidade"] < 0 for h in mapa_horarios)
        or sum(h["quantidade"] for h in mapa_horarios) != pedidos
        or len({h["hora"] for h in mapa_horarios}) != len(mapa_horarios)
    ):
        raise ErroHistorico("A distribuição horária é inconsistente.")
    if not mapa_finalizacoes or any(
        type(v["quantidade"]) is not int or v["quantidade"] < 0
        or type(v["percentual"]) not in (int, float)
        or not (0 <= v["percentual"] <= 100)
        for v in mapa_finalizacoes.values()
    ):
        raise ErroHistorico("Finalizações inválidas.")

    return {
        "versao": VERSAO,
        "operacao": cliente,
        "identificador": _identificador_operacao(cliente),
        "competencia": competencia,
        "periodo": dados["periodo"],
        "pedidos": pedidos,
        "areas": sorted(mapa_areas, key=lambda a: a["nome"].casefold()),
        "horarios": sorted(mapa_horarios, key=lambda h: h["hora"]),
        "finalizacoes": mapa_finalizacoes,
    }


class Historico:
    """Consulta e registra competências em uma pasta-base local ou de rede."""

    def __init__(self, pasta_base):
        self.pasta_base = Path(pasta_base)
        if not self.pasta_base.is_dir():
            raise ErroHistorico(
                "Pasta-base indisponível. Verifique o acesso à rede antes de continuar."
            )

    def _arquivo(self, cliente, competencia):
        return self.pasta_base / "historico" / _identificador_operacao(cliente) / f"{competencia}.json"

    def consultar(self, cliente, competencia):
        """Devolve o registro completo ou None; nunca trata corrupção como ausência."""
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", competencia):
            raise ErroHistorico("Competência inválida: use AAAA-MM.")
        if not self.pasta_base.is_dir():
            raise ErroHistorico("Histórico compartilhado indisponível; não foi tratado como vazio.")
        arquivo = self._arquivo(cliente, competencia)
        try:
            arquivo.stat()
        except FileNotFoundError:
            return None
        except OSError as erro:
            raise ErroHistorico(f"Não foi possível consultar o histórico: {arquivo}") from erro
        try:
            registro = json.loads(arquivo.read_text(encoding="utf-8"))
            payload = registro["dados"]
            esperado = hashlib.sha256(_json_canonico(payload).encode("utf-8")).hexdigest()
            if (registro["sha256"] != esperado or payload["versao"] != VERSAO
                    or payload["competencia"] != competencia
                    or payload["identificador"] != _identificador_operacao(cliente)):
                raise ValueError("Assinatura ou identificação inconsistente.")
            return payload
        except (OSError, ValueError, KeyError, TypeError) as erro:
            raise ErroHistorico(f"Histórico ilegível/inconsistente: {arquivo}") from erro

    def registrar(self, dados):
        """Registra uma vez; retorna 'criado' ou 'existente', nunca sobrescreve.

        Usa um diretório de bloqueio por competência e arquivo temporário
        na mesma pasta. Um bloqueio abandonado exige revisão manual segura.
        """
        payload = _resumo(dados)
        cliente = payload["operacao"]
        competencia = payload["competencia"]
        arquivo = self._arquivo(cliente, competencia)
        pasta = arquivo.parent
        # Nunca recriar silenciosamente a pasta-base do servidor se ela sumir.
        # Criamos apenas os dois níveis internos, sem parents=True: se a base
        # desaparecer entre a checagem e a gravação, a operação deverá falhar.
        if not self.pasta_base.is_dir():
            raise ErroHistorico(
                "Pasta-base do histórico indisponível. Nenhum registro foi criado."
            )
        try:
            (self.pasta_base / "historico").mkdir(exist_ok=True)
            pasta.mkdir(exist_ok=True)
        except OSError as erro:
            raise ErroHistorico(
                "Não foi possível preparar a pasta do histórico no compartilhamento."
            ) from erro
        bloqueio = pasta / f".{competencia}.lock"
        try:
            bloqueio.mkdir()  # criação exclusiva no compartilhamento
        except FileExistsError as erro:
            raise HistoricoEmUso(
                f"A competência {competencia} está em uso. Tente novamente mais tarde; "
                "se persistir, peça verificação do bloqueio à equipe responsável."
            ) from erro

        temporario = None
        try:
            atual = self.consultar(cliente, competencia)
            if atual is not None:
                if _json_canonico(atual) == _json_canonico(payload):
                    return "existente", arquivo
                raise ConflitoHistorico(
                    f"Já existe um registro diferente para {cliente}, {competencia}. "
                    "Nenhuma informação foi substituída."
                )

            registro = {
                "dados": payload,
                "sha256": hashlib.sha256(_json_canonico(payload).encode("utf-8")).hexdigest(),
            }
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", prefix=".registro_", suffix=".tmp",
                dir=pasta, delete=False,
            ) as aberto:
                temporario = Path(aberto.name)
                json.dump(registro, aberto, ensure_ascii=False, sort_keys=True, indent=2)
                aberto.write("\n")
                aberto.flush()
                os.fsync(aberto.fileno())
            os.replace(temporario, arquivo)
            return "criado", arquivo
        finally:
            if temporario is not None:
                temporario.unlink(missing_ok=True)
            bloqueio.rmdir()

    def mes_anterior(self, dados):
        """Encontra somente o mês imediatamente anterior da mesma operação."""
        competencia = _competencia(dados["periodo"])
        primeiro_dia = datetime.strptime(competencia + "-01", "%Y-%m-%d").date()
        anterior = (primeiro_dia - timedelta(days=1)).strftime("%Y-%m")
        return self.consultar(dados["cliente"], anterior)