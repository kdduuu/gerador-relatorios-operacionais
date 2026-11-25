"""Interface Windows: PDF, histórico compartilhado e backup.

A configuração é por usuário Windows; nenhuma pasta corporativa é embutida.
O histórico é consultado antes da geração e o resultado é mostrado por etapa.
"""

import json
import os
import tempfile
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

from src.backup_historico import BackupHistorico
from src.fluxo_operacional import executar_fluxo, inspecionar_fluxo
from src.gerar_relatorio import nome_legivel, nome_sugerido
from src.historico import Historico
from src.indicadores import calcular_indicadores
from src.ler_pdf import processar_pdf_completo

# Paleta baseada na identidade do relatório gerencial.
GRAFITE = "#202423"
VERDE = "#05D84A"
FUNDO = "#F2F5F3"
BRANCO = "#FFFFFF"
TEXTO = "#242A27"
CINZA = "#66716B"
BORDA = "#E4E9E6"
VERDE_CLARO = "#E8FAEC"
AMARELO_CLARO = "#FFF7E7"


def formatar_numero(numero):
    """Exibe inteiros como 1.469, seguindo o padrão brasileiro."""
    return f"{numero:,}".replace(",", ".")


def caminho_configuracao():
    """Configuração privada de cada usuário Windows (nunca no GitHub)."""
    base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    return base / "Portfolio" / "GeradorRelatorios" / "config.json"


def ler_configuracao(caminho):
    """Falha de forma segura: configuração inválida nunca ativa gravação."""
    try:
        conteudo = json.loads(Path(caminho).read_text(encoding="utf-8"))
        if conteudo.get("versao") != 1:
            return None
        historico, backup = conteudo["historico"], conteudo["backup"]
        if not isinstance(historico, str) or not isinstance(backup, str):
            return None
        if not historico.strip() or not backup.strip():
            return None
        return Path(historico.strip()), Path(backup.strip())
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def salvar_configuracao(caminho, historico, backup):
    """Salva caminhos sem credenciais; não cria pastas corporativas."""
    historico, backup = str(historico).strip(), str(backup).strip()
    if not historico or not backup:
        raise ValueError("Informe as duas pastas para habilitar a geração integrada.")
    if not Path(historico).is_absolute() or not Path(backup).is_absolute():
        raise ValueError("Use caminhos completos para as duas pastas (local ou UNC).")
    # Só aceitar bases já existentes, diferentes e não aninhadas.
    Historico(historico)
    BackupHistorico(historico, backup)
    arquivo = Path(caminho)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    temporario = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", prefix=".config_", suffix=".tmp",
            dir=arquivo.parent, delete=False,
        ) as aberto:
            temporario = Path(aberto.name)
            json.dump({"versao": 1, "historico": historico, "backup": backup},
                      aberto, ensure_ascii=False, indent=2)
            aberto.write("\n")
            aberto.flush()
            os.fsync(aberto.fileno())
        os.replace(temporario, arquivo)
    finally:
        if temporario is not None:
            temporario.unlink(missing_ok=True)


def descricao_plano(plano):
    """Texto curto de prévia, sem prometer que o PDF já existe."""
    comparativo = (
        f"Comparativo com {plano.mes_anterior} disponível."
        if plano.mes_anterior else
        "Sem mês anterior: relatório sem comparativo."
    )
    registro = "Mês já cadastrado." if plano.registro_atual == "existente" else "Mês ainda não cadastrado."
    return f"{comparativo} {registro}"


def descricao_resultado(resultado):
    """Não confunde PDF salvo com histórico e backup concluídos."""
    return (f"PDF: salvo | Histórico: {resultado.historico} | "
            f"Backup: {resultado.backup}.")


def pasta_padrao_de_saida():
    """Cria uma pasta local de relatórios, sem misturar PDFs de origem e saída.

    Se Documentos não existir ou a criação for bloqueada, usa uma pasta
    acessível como alternativa; o usuário sempre pode escolher outro destino.
    """
    documentos = Path.home() / "Documents"
    base = documentos if documentos.is_dir() else Path.home()
    pasta = base / "Relatorios Operacionais"
    try:
        pasta.mkdir(parents=True, exist_ok=True)
    except OSError:
        return base
    return pasta


class Aplicativo(tk.Tk):
    """Janela principal: nenhuma informação operacional é digitada manualmente."""

    def __init__(self):
        super().__init__()
        self.title("Gerador de Relatórios Operacionais")
        self.geometry("960x680")
        self.minsize(820, 640)
        self.configure(bg=FUNDO)

        self.origem = None
        self.origem_id = None
        self.dados = None
        self.ultimo_gerado = None
        self.ultima_pasta_saida = None
        # A sessão só registra o que foi concluído durante esta execução.
        self.geracoes_sessao = {}
        self.plano = None
        configuracao = ler_configuracao(caminho_configuracao())
        self.pasta_historico, self.pasta_backups = configuracao or (None, None)
        self.status = tk.StringVar(value="Selecione um PDF do AtivMob para começar.")

        self._montar_tela()

    def _rotulo(self, pai, texto, tamanho=10, cor=TEXTO, negrito=False, **opcoes):
        return tk.Label(
            pai, text=texto, bg=pai.cget("bg"), fg=cor,
            font=("Segoe UI", tamanho, "bold" if negrito else "normal"),
            justify="left", anchor="w", **opcoes,
        )

    def _montar_tela(self):
        topo = tk.Frame(self, bg=GRAFITE, height=112)
        topo.pack(fill="x")
        topo.pack_propagate(False)
        tk.Frame(topo, bg=VERDE, height=4).pack(fill="x")
        faixa = tk.Frame(topo, bg=GRAFITE, padx=30, pady=18)
        faixa.pack(fill="both", expand=True)
        tk.Button(
            faixa, text="CONFIGURAR HISTÓRICO", command=self.configurar_historico,
            bg=GRAFITE, fg=BRANCO, activebackground="#39423D", activeforeground=BRANCO,
            relief="flat", bd=0, font=("Segoe UI", 9), cursor="hand2",
        ).pack(side="right", anchor="ne", pady=8)
        self._rotulo(faixa, "OPERACIONAL", 19, VERDE, True).pack(anchor="w")
        self._rotulo(
            faixa, "GERADOR DE RELATÓRIOS OPERACIONAIS", 11, BRANCO, True
        ).pack(anchor="w", pady=(4, 0))

        corpo = tk.Frame(self, bg=FUNDO, padx=24, pady=22)
        corpo.pack(fill="both", expand=True)
        corpo.columnconfigure(0, weight=4)
        corpo.columnconfigure(1, weight=6)
        corpo.rowconfigure(0, weight=1)

        esquerda = tk.Frame(corpo, bg=BRANCO, padx=22, pady=20, highlightthickness=1,
                            highlightbackground=BORDA)
        esquerda.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        direita = tk.Frame(corpo, bg=BRANCO, padx=22, pady=20, highlightthickness=1,
                           highlightbackground=BORDA)
        direita.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

        self._rotulo(esquerda, "01  /  SELECIONAR ARQUIVO", 10, CINZA, True).pack(anchor="w")
        self._rotulo(esquerda, "PDF do AtivMob", 17, TEXTO, True).pack(anchor="w", pady=(12, 5))
        self._rotulo(
            esquerda, "Escolha o arquivo Visão Geral Entregas. O original não será alterado.",
            10, CINZA, wraplength=280,
        ).pack(anchor="w")

        tk.Button(
            esquerda, text="Selecionar PDF do AtivMob", command=self.selecionar_pdf,
            bg=GRAFITE, fg=BRANCO, activebackground="#39423D", activeforeground=BRANCO,
            relief="flat", bd=0, padx=14, pady=12, cursor="hand2",
            font=("Segoe UI", 10, "bold"),
        ).pack(fill="x", pady=(20, 8))
        self.arquivo_label = self._rotulo(
            esquerda, "Nenhum arquivo selecionado", 9, CINZA, wraplength=275
        )
        self.arquivo_label.pack(anchor="w")

        tk.Frame(esquerda, bg=BORDA, height=1).pack(fill="x", pady=27)
        self._rotulo(esquerda, "02  /  GERAR RELATÓRIO", 10, CINZA, True).pack(anchor="w")
        self._rotulo(
            esquerda, "Confira o resumo ao lado e escolha onde salvar o PDF gerencial.",
            10, CINZA, wraplength=280,
        ).pack(anchor="w", pady=(12, 15))

        self.botao_gerar = tk.Button(
            esquerda, text="Gerar relatório PDF", command=self.gerar_pdf,
            bg=VERDE, fg=GRAFITE, activebackground="#00BD3E", activeforeground=GRAFITE,
            disabledforeground="#777F7A", relief="flat", bd=0, padx=14, pady=12,
            cursor="hand2", font=("Segoe UI", 11, "bold"), state="disabled",
        )
        self.botao_gerar.pack(fill="x")
        self.botao_abrir = tk.Button(
            esquerda, text="Abrir último PDF gerado", command=self.abrir_relatorio,
            bg=BRANCO, fg=TEXTO, relief="flat", bd=0, pady=10,
            font=("Segoe UI", 9), state="disabled",
        )
        self.botao_abrir.pack(fill="x", pady=(7, 0))

        self._rotulo(direita, "PRÉVIA DOS DADOS", 10, CINZA, True).pack(anchor="w")
        self.cliente_label = self._rotulo(
            direita, "Nenhum relatório carregado", 15, TEXTO, True, wraplength=420
        )
        self.cliente_label.pack(anchor="w", pady=(13, 5))
        self.periodo_label = self._rotulo(direita, "Competência: —", 10, CINZA)
        self.periodo_label.pack(anchor="w")

        indicadores = tk.Frame(direita, bg=FUNDO, padx=12, pady=15)
        indicadores.pack(fill="x", pady=(16, 13))
        for i in range(3):
            indicadores.columnconfigure(i, weight=1)
        self.metricas = {}
        for coluna, (chave, titulo) in enumerate([
            ("pedidos", "PEDIDOS"), ("areas", "ÁREAS"), ("entregues", "ENTREGUES")
        ]):
            bloco = tk.Frame(indicadores, bg=FUNDO)
            bloco.grid(row=0, column=coluna, sticky="ew")
            self._rotulo(bloco, titulo, 8, CINZA, True).pack(anchor="w")
            numero = self._rotulo(bloco, "—", 19, TEXTO, True)
            numero.pack(anchor="w", pady=(5, 0))
            self.metricas[chave] = numero

        self.destaques_label = self._rotulo(
            direita, "Os indicadores aparecerão após selecionar o PDF.",
            10, TEXTO, wraplength=420,
        )
        self.destaques_label.pack(anchor="w")
        tk.Frame(direita, bg=BORDA, height=1).pack(fill="x", pady=14)
        self._rotulo(direita, "AVISOS DO DOCUMENTO", 10, CINZA, True).pack(anchor="w")
        caixa_avisos = tk.Frame(direita, bg=BRANCO)
        caixa_avisos.pack(fill="x", pady=(9, 0))
        barra = tk.Scrollbar(caixa_avisos)
        barra.pack(side="right", fill="y")
        self.avisos_texto = tk.Text(
            caixa_avisos, height=4, width=34, wrap="word", bg=BRANCO, fg=CINZA,
            font=("Segoe UI", 9), relief="flat", bd=0, padx=0, pady=0,
            yscrollcommand=barra.set,
        )
        self.avisos_texto.pack(side="left", fill="x", expand=True)
        barra.configure(command=self.avisos_texto.yview)
        self._preencher_avisos("Nenhum documento analisado.")
        # Confirmação permanente: não depende da janela de mensagem temporária.
        self.painel_estado = tk.Frame(
            direita, bg=FUNDO, padx=12, pady=9,
            highlightthickness=1, highlightbackground=BORDA,
        )
        self.painel_estado.pack(side="bottom", fill="x", pady=(12, 0))
        self.estado_titulo = tk.Label(
            self.painel_estado, text="AGUARDANDO PDF", bg=FUNDO, fg=CINZA,
            font=("Segoe UI", 10, "bold"), anchor="w",
        )
        self.estado_titulo.pack(fill="x")
        self.estado_detalhe = tk.Label(
            self.painel_estado,
            text="Selecione um arquivo para começar.",
            bg=FUNDO, fg=CINZA, font=("Segoe UI", 9),
            anchor="w", justify="left", wraplength=400,
        )
        self.estado_detalhe.pack(fill="x", pady=(4, 0))


        rodape = tk.Frame(self, bg=FUNDO, padx=26, pady=12)
        rodape.pack(fill="x")
        self._rotulo(rodape, "Fonte: AtivMob", 9, CINZA).pack(side="right")
        self._rotulo(rodape, "", 9, CINZA, textvariable=self.status).pack(
            side="left", fill="x", expand=True
        )

    def _marcar_estado(self, fase, detalhe):
        """Mostra de modo persistente o estágio atual do PDF selecionado.

        O estado "gerado" só é usado depois de gravar o arquivo com sucesso.
        """
        estilos = {
            "aguardando": ("AGUARDANDO PDF", FUNDO, CINZA),
            "analisando": ("VALIDANDO DOCUMENTO", FUNDO, CINZA),
            "gerando": ("GERANDO RELATÓRIO", FUNDO, CINZA),
            "pronto": ("PRONTO PARA GERAR", FUNDO, TEXTO),
            "gerado": ("RELATÓRIO CONCLUÍDO ✓", VERDE_CLARO, "#137A36"),
            "parcial": ("PDF SALVO — PENDÊNCIA", AMARELO_CLARO, "#8A560D"),
            "configurar": ("CONFIGURAÇÃO NECESSÁRIA", AMARELO_CLARO, "#8A560D"),
            "indisponivel": ("HISTÓRICO INDISPONÍVEL", AMARELO_CLARO, "#8A560D"),
            "erro": ("ATENÇÃO — NÃO GERADO", AMARELO_CLARO, "#8A560D"),
        }
        titulo, fundo, cor = estilos[fase]
        self.painel_estado.configure(bg=fundo)
        self.estado_titulo.configure(text=titulo, bg=fundo, fg=cor)
        resumo = detalhe if len(detalhe) <= 200 else detalhe[:197] + "..."
        self.estado_detalhe.configure(text=resumo, bg=fundo, fg=TEXTO)
        self.botao_gerar.configure(
            text="Gerar novamente PDF" if fase in ("gerado", "parcial") else "Gerar relatório PDF"
        )

    @staticmethod
    def _identificacao_arquivo(caminho):
        """Distingue PDFs de origem alterados desde a geração anterior."""
        try:
            info = Path(caminho).stat()
            return info.st_size, info.st_mtime_ns
        except OSError:
            return None

    def _preencher_avisos(self, mensagem):
        self.avisos_texto.configure(state="normal")
        self.avisos_texto.delete("1.0", "end")
        self.avisos_texto.insert("1.0", mensagem)
        self.avisos_texto.configure(state="disabled")

    def configurar_historico(self):
        """Configuração pontual; aceita UNC digitado e não escreve no servidor."""
        janela = tk.Toplevel(self)
        janela.title("Configurar histórico e backup")
        janela.configure(bg=BRANCO)
        janela.geometry("725x310")
        janela.resizable(False, False)
        janela.transient(self)
        janela.grab_set()

        corpo = tk.Frame(janela, bg=BRANCO, padx=24, pady=18)
        corpo.pack(fill="both", expand=True)
        self._rotulo(corpo, "PASTAS COMPARTILHADAS", 12, TEXTO, True).pack(anchor="w")
        self._rotulo(
            corpo, "Informe pastas já existentes. Prefira caminhos UNC (\\\\servidor\\pasta).",
            9, CINZA,
        ).pack(anchor="w", pady=(5, 12))

        historico = tk.StringVar(value=str(self.pasta_historico or ""))
        backup = tk.StringVar(value=str(self.pasta_backups or ""))

        for titulo, variavel in (("Pasta do histórico", historico), ("Pasta de backups", backup)):
            self._rotulo(corpo, titulo, 9, TEXTO, True).pack(anchor="w", pady=(4, 3))
            linha = tk.Frame(corpo, bg=BRANCO)
            linha.pack(fill="x")
            tk.Entry(linha, textvariable=variavel, font=("Segoe UI", 9)).pack(
                side="left", fill="x", expand=True, ipady=3,
            )
            tk.Button(
                linha, text="Procurar...", command=lambda v=variavel: self._escolher_pasta(janela, v),
                bg=FUNDO, relief="flat", font=("Segoe UI", 9), padx=8,
            ).pack(side="left", padx=(8, 0))

        self._rotulo(
            corpo,
            "Em produção, os backups devem ter proteção independente do histórico.",
            9, CINZA,
        ).pack(anchor="w", pady=(10, 9))

        def confirmar():
            try:
                salvar_configuracao(caminho_configuracao(), historico.get(), backup.get())
            except Exception as erro:  # noqa: BLE001
                messagebox.showerror("Configuração inválida", str(erro), parent=janela)
                return
            self.pasta_historico = Path(historico.get().strip())
            self.pasta_backups = Path(backup.get().strip())
            self.plano = None
            self.geracoes_sessao.clear()  # Outra configuração => outro histórico.
            janela.destroy()
            self._atualizar_plano()

        tk.Button(
            corpo, text="Salvar configuração", command=confirmar,
            bg=VERDE, fg=GRAFITE, activebackground="#00BD3E", relief="flat",
            font=("Segoe UI", 10, "bold"), padx=12, pady=7,
        ).pack(anchor="e")
        janela.wait_window()

    @staticmethod
    def _escolher_pasta(janela, variavel):
        pasta = filedialog.askdirectory(parent=janela, title="Selecionar pasta existente")
        if pasta:
            variavel.set(pasta)

    def _atualizar_plano(self):
        """Consulta histórico sem gravar; só habilita o botão se for seguro."""
        self.plano = None
        self.botao_gerar.configure(state="disabled")
        if self.dados is None or self.origem is None:
            self._marcar_estado("aguardando", "Selecione um PDF do AtivMob para começar.")
            return
        if self.pasta_historico is None or self.pasta_backups is None:
            self._marcar_estado(
                "configurar", "Configure as pastas de histórico e backup no topo da janela.",
            )
            self.status.set("Configuração do histórico necessária.")
            return
        try:
            self.plano = inspecionar_fluxo(
                self.dados, self.pasta_historico, self.pasta_backups,
            )
        except Exception as erro:  # noqa: BLE001
            self._marcar_estado("indisponivel", f"Geração bloqueada: {erro}")
            self.status.set("Corrija o histórico e use 'CONFIGURAR HISTÓRICO' para verificar.")
            return

        self.botao_gerar.configure(state="normal")
        chave = str(self.origem.resolve())
        registro = self.geracoes_sessao.get(chave)
        if registro and registro["origem_id"] == self._identificacao_arquivo(self.origem):
            destino = registro["destino"]
            if destino.is_file() and destino.stat().st_size > 0:
                self.ultimo_gerado = destino
                self.botao_abrir.configure(state="normal", cursor="hand2")
                self._marcar_estado(
                    "gerado" if registro["estado"] == "concluido" else "parcial",
                    registro["detalhe"],
                )
                return
        self._marcar_estado("pronto", descricao_plano(self.plano))
        self.status.set("Prévia do histórico consultada. Pronto para gerar.")

    def selecionar_pdf(self):
        caminho = filedialog.askopenfilename(
            parent=self,
            title="Selecionar PDF do AtivMob",
            filetypes=[("Arquivos PDF", "*.pdf")],
        )
        if caminho:
            self.carregar_pdf(Path(caminho))

    def carregar_pdf(self, caminho):
        """Valida o arquivo escolhido antes de habilitar a geração."""
        self.dados = None
        self.origem = None
        self.origem_id = None
        self.plano = None
        self.ultimo_gerado = None
        self.botao_gerar.configure(state="disabled")
        self.botao_abrir.configure(state="disabled")
        self._marcar_estado("analisando", "Conferindo os dados do AtivMob...")
        self.status.set("Analisando o documento...")
        self.update_idletasks()
        try:
            dados = processar_pdf_completo(caminho)
            indicadores = calcular_indicadores(dados)
        except Exception as erro:  # noqa: BLE001
            self.arquivo_label.configure(text="Nenhum PDF válido selecionado")
            self.cliente_label.configure(text="Documento não reconhecido")
            self.periodo_label.configure(text="Competência: —")
            for rotulo in self.metricas.values():
                rotulo.configure(text="—")
            self.destaques_label.configure(text="Selecione outro PDF do AtivMob.")
            self._preencher_avisos("A validação não foi concluída.")
            self.status.set("Não foi possível validar o PDF.")
            self._marcar_estado("erro", "O PDF não foi validado. Selecione outro arquivo.")
            messagebox.showerror("PDF inválido", f"Não foi possível ler este relatório:\n\n{erro}", parent=self)
            return

        self.origem = Path(caminho)
        self.origem_id = self._identificacao_arquivo(self.origem)
        self.dados = dados
        self.arquivo_label.configure(text=self.origem.name)
        self.cliente_label.configure(text=dados["cliente"])
        self.periodo_label.configure(text=f'Período: {dados["periodo"]}')
        self.metricas["pedidos"].configure(text=formatar_numero(dados["pedidos"]))
        self.metricas["areas"].configure(text=str(len(dados["areas"])))
        self.metricas["entregues"].configure(
            text=formatar_numero(dados["finalizacoes"]["Entregue"]["quantidade"])
        )
        maior = indicadores["maior_area"]
        pico = indicadores["pico"]
        concentracao = f'{indicadores["concentracao_duas"]:.1f}'.replace(".", ",")
        texto = (
            f'Maior área: {nome_legivel(maior["nome"])}  •  '
            f'Top 2 áreas: {concentracao}%  •  '
            f'Pico: {pico["hora"] if pico else "não identificado"}'
        ) if maior else "Nenhuma área com registros no período."
        self.destaques_label.configure(text=texto)

        avisos = dados.get("avisos", [])
        self._preencher_avisos(
            "\n".join(f"• {aviso}" for aviso in avisos)
            if avisos else "Nenhum aviso de extração identificado."
        )
        self._atualizar_plano()

    def gerar_pdf(self):
        if self.dados is None or self.origem is None:
            return
        if (self.origem_id is None or
                self._identificacao_arquivo(self.origem) != self.origem_id):
            self.botao_gerar.configure(state="disabled")
            self._marcar_estado("erro", "O PDF original mudou ou não está acessível. Selecione-o novamente.")
            return
        if self.pasta_historico is None or self.pasta_backups is None:
            self._atualizar_plano()
            return
        # Reconsulta antes de salvar: outro computador pode ter atualizado o mês.
        self._atualizar_plano()
        if self.plano is None:
            messagebox.showerror(
                "Histórico indisponível",
                "O histórico não está pronto. Verifique a configuração antes de gerar.",
                parent=self,
            )
            return
        caminho = filedialog.asksaveasfilename(
            parent=self,
            title="Salvar relatório gerencial",
            initialdir=str(self.ultima_pasta_saida or pasta_padrao_de_saida()),
            initialfile=nome_sugerido(self.dados),
            defaultextension=".pdf",
            filetypes=[("Arquivos PDF", "*.pdf")],
        )
        if not caminho:
            return
        if self._identificacao_arquivo(self.origem) != self.origem_id:
            self.botao_gerar.configure(state="disabled")
            self._marcar_estado("erro", "O PDF original mudou. Selecione-o novamente.")
            return
        destino = Path(caminho)
        if destino.resolve() == self.origem.resolve():
            messagebox.showerror(
                "Arquivo de origem", "O relatório não pode substituir o PDF original do AtivMob.",
                parent=self,
            )
            return
        substituir = False
        if destino.exists():
            substituir = messagebox.askyesno(
                "Arquivo já existente",
                f"O arquivo {destino.name} já existe. Deseja substituí-lo?",
                parent=self,
            )
            if not substituir:
                return

        self._marcar_estado("gerando", "Gerando o PDF e registrando o histórico...")
        self.status.set("Processando relatório, histórico e backup...")
        self.botao_gerar.configure(state="disabled")
        self.update_idletasks()
        try:
            resultado = executar_fluxo(
                self.dados, destino, self.pasta_historico, self.pasta_backups,
                origem_pdf=self.origem, autorizar_substituicao_pdf=substituir,
            )
        except Exception as erro:  # noqa: BLE001
            self.botao_gerar.configure(state="normal")
            self._marcar_estado("erro", "A geração integrada foi interrompida. Nenhum sucesso foi confirmado.")
            self.status.set("Falha no processamento integrado.")
            messagebox.showerror("Falha ao gerar", f"Não foi possível concluir:\n\n{erro}", parent=self)
            return

        self.ultimo_gerado = resultado.destino_pdf
        self.ultima_pasta_saida = destino.parent
        hora = datetime.now().strftime("%H:%M")
        detalhe = f"Às {hora}. {descricao_resultado(resultado)}"
        if resultado.estado == "parcial":
            detalhe += " Verifique a pendência antes de enviar ao cliente."
        self.geracoes_sessao[str(self.origem.resolve())] = {
            "origem_id": self._identificacao_arquivo(self.origem),
            "destino": resultado.destino_pdf,
            "hora": hora,
            "estado": resultado.estado,
            "detalhe": detalhe,
        }
        self.botao_gerar.configure(state="normal")
        self.botao_abrir.configure(state="normal", cursor="hand2")
        self._marcar_estado("gerado" if resultado.estado == "concluido" else "parcial", detalhe)
        self.status.set(f"PDF salvo: {resultado.destino_pdf.name}; histórico: {resultado.historico}; "
                        f"backup: {resultado.backup}")
        if resultado.estado == "parcial":
            messagebox.showwarning(
                "PDF salvo com pendência",
                f"PDF salvo em:\n{resultado.destino_pdf}\n\n"
                f"{descricao_resultado(resultado)}\n\n"
                f"Pendência: {resultado.detalhe}\n"
                "Solicite a verificação antes de considerar a operação concluída.",
                parent=self,
            )
        else:
            messagebox.showinfo(
                "Relatório concluído",
                f"PDF salvo em:\n{resultado.destino_pdf}\n\n"
                f"{descricao_resultado(resultado)}\n\n"
                "Revise o documento antes de enviar ao cliente.",
                parent=self,
            )

    def abrir_relatorio(self):
        if self.ultimo_gerado is None:
            return
        try:
            os.startfile(self.ultimo_gerado)  # Windows: abre no leitor padrão de PDFs.
        except Exception as erro:  # noqa: BLE001
            messagebox.showerror("Não foi possível abrir", str(erro), parent=self)


def main():
    Aplicativo().mainloop()


if __name__ == "__main__":
    main()