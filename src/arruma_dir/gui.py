from __future__ import annotations

import json
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from arruma_dir.hardware import HardwareProfile

from arruma_dir.gui_charts import LazyChartDeck
from arruma_dir.hardware import detect_hardware, disk_usage_for, normalize_performance_mode

from arruma_dir.logging_utils import close_logger, create_operation_logger, format_log_event
from arruma_dir.organizer import (
    ApplyResult,
    ScanResult,
    apply_plan,
    choose_duplicate_keeper,
    default_documents_path,
    duplicate_hash_label,
    is_batch_safe_duplicate_group,
    move_duplicates_to_quarantine,
    move_files_to_quarantine,
    rollback_moves,
    scan_directory,
    scan_name_standardization,
    write_scan_json,
)
from arruma_dir.project_organizer import (
    DEFAULT_ROOT as DEFAULT_PROJECTS_ROOT,
    REPORTS_DIR,
    DuplicateOperation,
    ProjectApplyResult,
    ProjectReport,
    apply_report as apply_project_report,
    scan_projects,
    state_path,
)
from arruma_dir.safety import SafetyCheck, check_organization_root


MODE_DOCUMENTS = "documents"
MODE_PROJECTS = "projects"

APP_BG = "#f5f7fb"
HEADER_BG = "#172033"
HEADER_FG = "#f8fafc"
MUTED_FG = "#64748b"
PANEL_BG = "#ffffff"
ACCENT = "#2563eb"


class ArrumaDirApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Arruma Dir")
        self.minsize(1180, 760)
        self.configure(bg=APP_BG)
        self.scan_result: ScanResult | None = None
        self.project_report: ProjectReport | None = None
        self.active_mode: str | None = None
        self.active_root: str | None = None
        self.cancel_event = threading.Event()
        self.duplicate_rows: dict[str, dict[str, object]] = {}
        self.work_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.busy = False
        self.rollback_move_pairs: list[tuple[str, str]] = []
        self.rollback_root: str | None = None
        self.rollback_mode: str | None = None
        self.rollback_label = ""

        self.mode_var = tk.StringVar(value=MODE_DOCUMENTS)
        self.path_var = tk.StringVar(value=str(default_documents_path()))
        self.compat_var = tk.BooleanVar(value=True)
        self.duplicates_var = tk.BooleanVar(value=True)
        self.full_duplicates_var = tk.BooleanVar(value=False)
        self.cad_duplicates_var = tk.BooleanVar(value=False)
        self.external_var = tk.BooleanVar(value=False)
        self.external_drives_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Pronto")
        self.hardware_profile: HardwareProfile | None = None
        self.performance_var = tk.StringVar(value="balanced")
        self.disk_usage_var = tk.StringVar(value="Uso do disco: (escolha uma pasta)")
        self.disk_percent_var = tk.DoubleVar(value=0.0)
        self.disk_usage_after_id: str | None = None
        self.safety_var = tk.StringVar(value="Escolha o local, gere uma previa e revise antes de aplicar.")
        self.next_step_var = tk.StringVar(value="1. Escolha o modo e a pasta. 2. Gere a previa. 3. Revise antes de aplicar.")
        self.summary_vars = {
            "planned": tk.StringVar(value="0"),
            "duplicates": tk.StringVar(value="0"),
            "possible": tk.StringVar(value="0"),
            "external": tk.StringVar(value="0"),
            "errors": tk.StringVar(value="0"),
        }
        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_text_var = tk.StringVar(value="")
        self.progress_is_indeterminate = False
        self.charts: LazyChartDeck | None = None

        self._configure_style()
        self._build_layout()
        self.path_var.trace_add("write", self._on_path_changed)
        self._update_mode_controls()
        self._set_action_buttons()
        self._on_path_changed()
        self.after(120, self._poll_queue)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", font=("Segoe UI", 9))
        style.configure("TFrame", background=APP_BG)
        style.configure("Panel.TFrame", background=PANEL_BG, relief="flat")
        style.configure("TLabel", background=APP_BG, foreground="#0f172a")
        style.configure("Muted.TLabel", background=APP_BG, foreground=MUTED_FG)
        style.configure("Panel.TLabel", background=PANEL_BG, foreground="#0f172a")
        style.configure("PanelMuted.TLabel", background=PANEL_BG, foreground=MUTED_FG)
        style.configure("Title.TLabel", background=HEADER_BG, foreground=HEADER_FG, font=("Segoe UI Semibold", 18))
        style.configure("Subtitle.TLabel", background=HEADER_BG, foreground="#cbd5e1", font=("Segoe UI", 9))
        style.configure("StatValue.TLabel", background=PANEL_BG, foreground="#0f172a", font=("Segoe UI Semibold", 18))
        style.configure("StatLabel.TLabel", background=PANEL_BG, foreground=MUTED_FG, font=("Segoe UI", 8))
        style.configure("TLabelframe", background=APP_BG, bordercolor="#d8dee9", relief="solid")
        style.configure("TLabelframe.Label", background=APP_BG, foreground="#334155", font=("Segoe UI Semibold", 9))
        style.configure("TButton", padding=(10, 6))
        style.configure("Primary.TButton", padding=(14, 7), foreground="#ffffff", background=ACCENT)
        style.configure("Stop.TButton", padding=(10, 6), foreground="#ffffff", background="#dc2626")
        style.map("Stop.TButton", background=[("active", "#b91c1c"), ("disabled", "#fca5a5")])
        style.map("Primary.TButton", background=[("active", "#1d4ed8"), ("disabled", "#94a3b8")])
        style.configure("Disk.Horizontal.TProgressbar", background=ACCENT, troughcolor="#e2e8f0")
        style.configure("Treeview", rowheight=26, font=("Segoe UI", 9), bordercolor="#e2e8f0", fieldbackground="#ffffff")
        style.configure("Treeview.Heading", font=("Segoe UI Semibold", 9), background="#e8edf5", foreground="#0f172a")

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        header = tk.Frame(self, bg=HEADER_BG, padx=18, pady=14)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Arruma Dir", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="Organizacao segura para Documentos e Projetos/CAD, sempre com previa antes de mover.",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        status_box = tk.Frame(header, bg=HEADER_BG)
        status_box.grid(row=0, column=1, rowspan=2, sticky="e")
        ttk.Label(status_box, textvariable=self.status_var, style="Subtitle.TLabel").pack(anchor="e")

        control_area = ttk.Frame(self, padding=(12, 12, 12, 8))
        control_area.grid(row=1, column=0, sticky="ew")
        control_area.columnconfigure(0, weight=3)
        control_area.columnconfigure(1, weight=2)
        control_area.columnconfigure(2, weight=2)

        source_box = ttk.LabelFrame(control_area, text="1. Modo e local", padding=(12, 10))
        source_box.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        source_box.columnconfigure(1, weight=1)

        mode_box = ttk.Frame(source_box)
        mode_box.grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Radiobutton(
            mode_box,
            text="Documentos / PARA",
            variable=self.mode_var,
            value=MODE_DOCUMENTS,
            command=self._on_mode_changed,
        ).pack(side="left")
        ttk.Radiobutton(
            mode_box,
            text="Projetos / CAD",
            variable=self.mode_var,
            value=MODE_PROJECTS,
            command=self._on_mode_changed,
        ).pack(side="left", padx=(18, 0))

        ttk.Label(source_box, text="Local").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(10, 0))
        path_entry = ttk.Entry(source_box, textvariable=self.path_var)
        path_entry.grid(row=1, column=1, sticky="ew", pady=(10, 0))
        ttk.Button(source_box, text="Escolher", command=self.choose_directory).grid(row=1, column=2, padx=(8, 0), pady=(10, 0))
        ttk.Label(source_box, textvariable=self.safety_var, style="PanelMuted.TLabel", wraplength=520).grid(
            row=2,
            column=0,
            columnspan=3,
            sticky="w",
            pady=(8, 0),
        )

        options = ttk.LabelFrame(control_area, text="2. Opcoes da previa", padding=(12, 10))
        options.grid(row=0, column=1, sticky="nsew", padx=(0, 10))

        self.compat_check = ttk.Checkbutton(options, text="Nomes compativeis", variable=self.compat_var)
        self.compat_check.grid(row=0, column=0, sticky="w")
        self.duplicates_check = ttk.Checkbutton(options, text="Buscar repetidos", variable=self.duplicates_var)
        self.duplicates_check.grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.full_duplicates_check = ttk.Checkbutton(
            options,
            text="Duplicatas completas (lento)",
            variable=self.full_duplicates_var,
        )
        self.full_duplicates_check.grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.cad_duplicates_check = ttk.Checkbutton(
            options,
            text="Incluir/organizar CAD",
            variable=self.cad_duplicates_var,
        )
        self.cad_duplicates_check.grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.external_check = ttk.Checkbutton(options, text="Vasculhar HDs externos", variable=self.external_var)
        self.external_check.grid(row=4, column=0, sticky="w", pady=(6, 0))
        self.external_drive_frame = ttk.Frame(options)
        self.external_drive_frame.grid(row=5, column=0, sticky="ew", pady=(6, 0))
        self.external_drive_frame.columnconfigure(0, weight=1)
        self.external_entry = ttk.Entry(self.external_drive_frame, textvariable=self.external_drives_var, width=34)
        self.external_entry.grid(row=0, column=0, sticky="ew")
        self.external_choose_button = ttk.Button(
            self.external_drive_frame,
            text="HD...",
            command=self.choose_external_drive,
            width=7,
        )
        self.external_choose_button.grid(row=0, column=1, padx=(6, 0))
        self.external_clear_button = ttk.Button(
            self.external_drive_frame,
            text="Limpar",
            command=self.clear_external_drives,
            width=8,
        )
        self.external_clear_button.grid(row=0, column=2, padx=(6, 0))
        performance_box = ttk.Frame(options)
        performance_box.grid(row=6, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(performance_box, text="Desempenho").pack(side="left", anchor="w")
        self.performance_combo = ttk.Combobox(
            performance_box,
            textvariable=self.performance_var,
            values=["safe", "balanced", "max"],
            state="readonly",
            width=12,
        )
        self.performance_combo.pack(side="left", padx=(8, 0), anchor="w")

        actions = ttk.LabelFrame(control_area, text="3. Acoes", padding=(12, 10))
        actions.grid(row=0, column=2, sticky="nsew")
        actions.columnconfigure(0, weight=1)

        self.scan_button = ttk.Button(actions, text="Gerar previa", command=self.scan, style="Primary.TButton")
        self.scan_button.grid(row=0, column=0, sticky="ew")
        self.standardize_button = ttk.Button(actions, text="Padronizar nomes", command=self.standardize_names)
        self.standardize_button.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.export_button = ttk.Button(actions, text="Exportar JSON", command=self.export_json)
        self.export_button.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.move_selected_button = ttk.Button(actions, text="Mover item selecionado", command=self.move_selected_duplicate)
        self.move_selected_button.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self.move_duplicates_button = ttk.Button(actions, text="Mover duplicatas seguras", command=self.move_duplicates)
        self.move_duplicates_button.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        self.apply_button = ttk.Button(actions, text="Aplicar plano", command=self.apply_organization)
        self.apply_button.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        self.populate_base_button = ttk.Button(actions, text="Popular base", command=self.populate_base)
        self.populate_base_button.grid(row=6, column=0, sticky="ew", pady=(8, 0))
        self.rollback_button = ttk.Button(actions, text="Voltar ultima acao", command=self.rollback_last_action)
        self.rollback_button.grid(row=7, column=0, sticky="ew", pady=(8, 0))
        self.stop_button = ttk.Button(actions, text="Parar Operacao", command=self.cancel_operation, style="Stop.TButton")
        self.stop_button.grid(row=8, column=0, sticky="ew", pady=(8, 0))
        self.stop_button.grid_remove()


        summary = ttk.Frame(self, padding=(12, 0, 12, 10))
        summary.grid(row=2, column=0, sticky="ew")
        summary.columnconfigure(5, weight=1)
        self._make_stat(summary, "Planejados", self.summary_vars["planned"], 0)
        self._make_stat(summary, "Duplicatas", self.summary_vars["duplicates"], 1)
        self._make_stat(summary, "Possiveis", self.summary_vars["possible"], 2)
        self._make_stat(summary, "Externos", self.summary_vars["external"], 3)
        self._make_stat(summary, "Erros", self.summary_vars["errors"], 4)
        next_box = ttk.Frame(summary, style="Panel.TFrame", padding=(12, 8))
        next_box.grid(row=0, column=5, sticky="ew", padx=(8, 0))
        next_box.columnconfigure(0, weight=1)
        ttk.Label(next_box, text="Proximo passo", style="PanelMuted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(next_box, textvariable=self.next_step_var, style="Panel.TLabel", wraplength=460).grid(
            row=1,
            column=0,
            sticky="ew",
            pady=(2, 0),
        )
        
        disk_frame = ttk.LabelFrame(self, text="Uso do Disco", padding=(12, 10))
        disk_frame.grid(row=4, column=0, sticky="ew", padx=12, pady=(0, 8))
        disk_frame.columnconfigure(0, weight=1)
        ttk.Label(disk_frame, textvariable=self.disk_usage_var, style="PanelMuted.TLabel").grid(
            row=0, column=0, sticky="ew"
        )
        ttk.Progressbar(disk_frame, variable=self.disk_percent_var, style="Disk.Horizontal.TProgressbar").grid(
            row=1, column=0, sticky="ew", pady=(4, 0)
        )


        notebook = ttk.Notebook(self)
        notebook.grid(row=3, column=0, sticky="nsew", padx=12, pady=(0, 8))

        self.plan_tree = self._make_tree(
            notebook,
            ("action", "category", "source", "destination", "reason"),
            ("Acao", "Topico", "Origem", "Destino", "Motivo"),
        )
        notebook.add(self.plan_tree.master, text="Plano")

        self.duplicate_tree = self._make_tree(
            notebook,
            ("kind", "size", "hash", "file", "differences"),
            ("Tipo", "Bytes", "Hash", "Arquivo", "Diferencas"),
        )
        notebook.add(self.duplicate_tree.master, text="Repetidos")

        summary_chart_frame = ttk.Frame(notebook)
        directory_chart_frame = ttk.Frame(notebook)
        self.charts = LazyChartDeck(summary_chart_frame, directory_chart_frame, log=self._append_log)

        notebook.add(summary_chart_frame, text="Tipos")
        notebook.add(directory_chart_frame, text="Diretórios")

        self.log = tk.Text(notebook, height=8, wrap="word")
        self.log.configure(state="disabled")
        notebook.add(self.log, text="Log")

        status = ttk.Frame(self, padding=(12, 0, 12, 12))
        status.grid(row=5, column=0, sticky="ew")
        status.columnconfigure(0, weight=2)
        status.columnconfigure(1, weight=1)
        ttk.Label(status, textvariable=self.status_var).grid(row=0, column=0, sticky="w")

        self.progress_frame = ttk.Frame(status)
        self.progress_frame.grid(row=0, column=1, sticky="ew", padx=(20, 0))
        self.progress_frame.columnconfigure(1, weight=1)

        self.progress_text_label = ttk.Label(self.progress_frame, textvariable=self.progress_text_var, width=34)
        self.progress_text_label.grid(row=0, column=0, sticky="w", padx=(0, 8))

        self.progress_bar = ttk.Progressbar(self.progress_frame, variable=self.progress_var)
        self.progress_bar.grid(row=0, column=1, sticky="ew")
        self.progress_frame.grid_remove()

    def _make_stat(self, parent: ttk.Frame, label: str, value: tk.StringVar, column: int) -> None:
        box = ttk.Frame(parent, style="Panel.TFrame", padding=(12, 8), width=130, height=70)
        box.grid(row=0, column=column, sticky="ew", padx=(0, 8))
        box.grid_propagate(False)
        ttk.Label(box, textvariable=value, style="StatValue.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(box, text=label, style="StatLabel.TLabel").grid(row=1, column=0, sticky="w")

    def _on_path_changed(self, *args: object) -> None:
        if self.disk_usage_after_id is not None:
            self.after_cancel(self.disk_usage_after_id)
        self.disk_usage_after_id = self.after(250, self._update_disk_usage)

    def _update_disk_usage(self) -> None:
        self.disk_usage_after_id = None
        path = self.path_var.get()
        if not path or not Path(path).exists():
            self.disk_usage_var.set("Uso do disco: (pasta invalida)")
            self.disk_percent_var.set(0.0)
            return
        try:
            usage = disk_usage_for(path)
            self.disk_usage_var.set(
                f"Uso do disco: {usage.used_gb:.1f} GB de {usage.total_gb:.1f} GB ({usage.free_gb:.1f} GB livres)"
            )
            self.disk_percent_var.set(usage.used_percent)
        except (OSError, ValueError):
            self.disk_usage_var.set("Uso do disco: (nao foi possivel ler)")
            self.disk_percent_var.set(0.0)

    def _clear_charts(self) -> None:
        if self.charts:
            self.charts.clear()

    def _update_pie_chart(self, summary_data: dict[str, int]) -> None:
        if self.charts:
            self.charts.update_file_summary(summary_data)

    def _update_directory_chart(self, directory_data: dict[str, int]) -> None:
        if self.charts:
            self.charts.update_directory_summary(directory_data)

    def _reset_summary(self) -> None:
        for value in self.summary_vars.values():
            value.set("0")
        self.next_step_var.set("1. Escolha o modo e a pasta. 2. Gere a previa. 3. Revise antes de aplicar.")

    def _set_summary(
        self,
        *,
        planned: int,
        duplicates: int,
        possible: int,
        external: int,
        errors: int,
        next_step: str,
    ) -> None:
        self.summary_vars["planned"].set(str(planned))
        self.summary_vars["duplicates"].set(str(duplicates))
        self.summary_vars["possible"].set(str(possible))
        self.summary_vars["external"].set(str(external))
        self.summary_vars["errors"].set(str(errors))
        self.next_step_var.set(next_step)

    def _document_scan_next_step(self, stats: dict[str, int]) -> str:
        if stats["errors"]:
            return "Veja a aba Log antes de aplicar. Corrija erros, gere nova previa e so depois mova arquivos."
        if not stats["planned_moves"] and not stats["exact_duplicate_groups"] and not stats["possible_duplicate_groups"]:
            return "Nada critico encontrado. A pasta ja parece organizada para este modo."

        options = ["revise Plano e Repetidos"]
        if stats["exact_duplicate_groups"]:
            options.append("mova duplicatas seguras")
        if stats["planned_moves"]:
            options.append("exporte JSON ou aplique o plano revisado")
        if stats["possible_duplicate_groups"]:
            options.append("decida duplicatas possiveis manualmente")
        return "Opcoes seguras: " + "; ".join(options) + "."

    def _project_scan_next_step(self, stats: dict[str, int]) -> str:
        if stats["errors"]:
            return "Veja a aba Log antes de aplicar. Em Projetos/CAD, corrija erros antes de mover qualquer item."
        if not stats["organization_moves"] and not stats["duplicate_moves"] and not stats["external_candidates"]:
            return "Nada relevante para mover. A estrutura de Projetos/CAD ja parece preservada."

        options = ["revise o plano sem quebrar referencias CAD"]
        if stats["organization_moves"]:
            options.append("aplique organizacao somente se os destinos estiverem corretos")
        if stats["duplicate_moves"]:
            options.append("mova duplicatas exatas para quarentena")
        if stats["external_candidates"]:
            options.append("clique Popular base depois de revisar os candidatos externos")
        return "Opcoes seguras: " + "; ".join(options) + "."

    def _make_tree(self, parent: ttk.Notebook, columns: tuple[str, ...], headings: tuple[str, ...]) -> ttk.Treeview:
        frame = ttk.Frame(parent)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
        y_scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        x_scroll = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        for column, heading in zip(columns, headings, strict=True):
            tree.heading(column, text=heading)
            tree.column(column, width=140 if column in {"action", "category", "size", "hash"} else 340)
        return tree

    def _on_mode_changed(self) -> None:
        self.scan_result = None
        self.project_report = None
        self.active_mode = None
        self.active_root = None
        if self.mode_var.get() == MODE_PROJECTS:
            current = Path(self.path_var.get())
            if current == default_documents_path():
                self.path_var.set(str(DEFAULT_PROJECTS_ROOT))
        elif self.mode_var.get() == MODE_DOCUMENTS:
            current = Path(self.path_var.get())
            if str(current).lower() == str(DEFAULT_PROJECTS_ROOT).lower():
                self.path_var.set(str(default_documents_path()))
        self._clear_tree(self.plan_tree)
        self._clear_tree(self.duplicate_tree)
        self._clear_charts()
        self.duplicate_rows.clear()
        self._reset_summary()
        self._update_mode_controls()
        self._set_action_buttons()
        self.status_var.set("Pronto")

    def _update_mode_controls(self) -> None:
        if self.mode_var.get() == MODE_PROJECTS:
            self.compat_check.configure(state="disabled")
            self.full_duplicates_check.configure(state="normal")
            self.cad_duplicates_check.configure(text="Incluir duplicatas CAD", state="normal")
            self.external_check.configure(state="normal")
            self.external_entry.configure(state="normal")
            self.external_choose_button.configure(state="normal")
            self.external_clear_button.configure(state="normal")
            self.safety_var.set("Projetos/CAD: arvores SolidWorks, Electrical, EPLAN e AutoCAD sao preservadas por padrao.")
        else:
            self.compat_check.configure(state="normal")
            self.full_duplicates_check.configure(state="normal")
            self.cad_duplicates_check.configure(text="Incluir/organizar CAD", state="normal")
            self.external_check.configure(state="disabled")
            self.external_entry.configure(state="disabled")
            self.external_choose_button.configure(state="disabled")
            self.external_clear_button.configure(state="disabled")
            self.safety_var.set("Documentos/PARA: gere uma previa, revise destinos e aplique somente com confirmacao.")

    def _set_action_buttons(self) -> None:
        has_document_scan = self.scan_result is not None and self.active_mode == MODE_DOCUMENTS
        has_project_scan = self.project_report is not None and self.active_mode == MODE_PROJECTS
        has_scan = has_document_scan or has_project_scan
        has_apply_plan = bool(
            (self.scan_result and self.scan_result.plan)
            or (self.project_report and self.project_report.organization)
        )
        has_duplicates = bool(
            (self.scan_result and self.scan_result.duplicates)
            or (self.project_report and self.project_report.duplicates)
        )
        normal = "normal"
        disabled = "disabled"
        self.scan_button.configure(state=disabled if self.busy else normal)
        self.standardize_button.configure(state=disabled if self.busy else normal)
        self.export_button.configure(state=normal if has_scan and not self.busy else disabled)
        self.apply_button.configure(state=normal if has_apply_plan and not self.busy else disabled)
        self.populate_base_button.configure(
            state=normal if self.mode_var.get() == MODE_PROJECTS and not self.busy else disabled
        )
        self.move_duplicates_button.configure(state=normal if has_duplicates and not self.busy else disabled)
        self.move_selected_button.configure(state=normal if has_duplicates and not self.busy else disabled)
        self.rollback_button.configure(state=normal if self.rollback_move_pairs and not self.busy else disabled)

    def choose_directory(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.path_var.get() or str(Path.home()))
        if selected:
            self.path_var.set(selected)

    def choose_external_drive(self) -> None:
        initial = self.external_drives_var.get().split(";")[0].strip() or self.path_var.get()
        selected = filedialog.askdirectory(initialdir=initial)
        if not selected:
            return
        current = self._parse_external_drives(allow_missing=True)
        selected_path = Path(selected)
        if all(path.resolve(strict=False) != selected_path.resolve(strict=False) for path in current):
            current.append(selected_path)
        self.external_drives_var.set("; ".join(str(path) for path in current))
        self.external_var.set(True)

    def clear_external_drives(self) -> None:
        self.external_drives_var.set("")

    def _parse_external_drives(self, *, allow_missing: bool = False) -> list[Path]:
        raw = self.external_drives_var.get().replace("\n", ";")
        drives: list[Path] = []
        seen: set[Path] = set()
        for item in raw.split(";"):
            value = item.strip().strip('"')
            if not value:
                continue
            path = Path(value)
            resolved = path.resolve(strict=False)
            if resolved in seen:
                continue
            if not allow_missing and not path.exists():
                raise FileNotFoundError(f"HD/pasta externa nao encontrada: {path}")
            seen.add(resolved)
            drives.append(path)
        return drives

    def _auto_select_mode_for_path(self) -> None:
        path = Path(self.path_var.get()).expanduser()
        if (path / "organizar").is_dir() and (path / "projetos").is_dir() and self.mode_var.get() != MODE_PROJECTS:
            self.mode_var.set(MODE_PROJECTS)
            self._update_mode_controls()
            self._append_log("Modo alterado para Projetos/CAD porque a raiz contem 'organizar' e 'projetos'.")

    def _check_current_root(self) -> SafetyCheck | None:
        path = self.path_var.get().strip()
        check = check_organization_root(path, mode=self.mode_var.get())
        if check.errors:
            messagebox.showerror("Local bloqueado", "\n".join(check.errors))
            return None
        if check.warnings:
            answer = messagebox.askyesno(
                "Confirmar local",
                "Avisos de seguranca:\n\n"
                + "\n".join(f"- {item}" for item in check.warnings)
                + "\n\nContinuar somente se este local for intencional.",
            )
            if not answer:
                return None
        return check

    def _require_same_root(self) -> bool:
        if not self.active_root:
            messagebox.showinfo("Arruma Dir", "Gere uma previa antes.")
            return False
        current = Path(self.path_var.get()).resolve(strict=False)
        scanned = Path(self.active_root).resolve(strict=False)
        if current != scanned:
            messagebox.showerror(
                "Local alterado",
                "O local foi alterado depois da previa. Gere uma nova previa antes de aplicar.",
            )
            return False
        return True

    def _confirm_action(self, title: str, message: str, *, code: str = "APLICAR") -> bool:
        answer = messagebox.askyesno(title, message)
        if not answer:
            return False
        typed = simpledialog.askstring(title, f"Digite {code} para confirmar:")
        if typed != code:
            self._append_log(f"{title}: cancelado por confirmacao invalida.")
            return False
        return True

    def cancel_operation(self) -> None:
        self.cancel_event.set()
        self.status_var.set("Cancelando operacao...")

    def _create_progress_callback(self) -> Callable[[int, int], None]:
        return lambda current, total: self.work_queue.put(("progress", (current, total)))

    def _remember_rollback(
        self,
        *,
        root: str | None,
        mode: str | None,
        label: str,
        moves: list[tuple[str, str]],
    ) -> None:
        self.rollback_root = root
        self.rollback_mode = mode
        self.rollback_label = label
        self.rollback_move_pairs = list(moves)
        self._set_action_buttons()
        if moves:
            self.next_step_var.set(
                f"Ultima acao pode ser revertida: {len(moves)} movimento(s). Use Voltar ultima acao se precisar."
            )

    def _clear_rollback(self) -> None:
        self.rollback_root = None
        self.rollback_mode = None
        self.rollback_label = ""
        self.rollback_move_pairs = []
        self._set_action_buttons()

    def rollback_last_action(self) -> None:
        if not self.rollback_move_pairs or not self.rollback_root:
            self._clear_rollback()
            messagebox.showinfo("Arruma Dir", "Nao ha uma acao recente para voltar.")
            return

        rollback_root = Path(self.rollback_root).resolve(strict=False)
        current_root = Path(self.path_var.get()).resolve(strict=False)
        if current_root != rollback_root:
            messagebox.showerror(
                "Local diferente",
                "O local atual nao e o mesmo da ultima acao.\n\n"
                f"Selecione novamente:\n{rollback_root}",
            )
            return

        label = self.rollback_label or "ultima acao"
        count = len(self.rollback_move_pairs)
        if not self._confirm_action(
            "Voltar ultima acao",
            f"Voltar {count} movimento(s) de {label} para o local original?\n\n"
            "A reversao usa o historico desta execucao. Nada sera apagado; se o local original estiver ocupado, "
            "o item fica onde esta e o erro aparece no log.",
            code="VOLTAR",
        ):
            return

        root = self.rollback_root
        mode = self.rollback_mode or self.active_mode or self.mode_var.get()
        moves = list(self.rollback_move_pairs)
        self._set_busy("Voltando ultima acao...")
        self.next_step_var.set("Reversao em andamento. Nao mova arquivos manualmente ate terminar.")
        progress_callback = self._create_progress_callback()
        thread = threading.Thread(
            target=self._rollback_worker,
            args=(root, mode, label, moves, self.cancel_event, progress_callback),
            daemon=True,
        )
        thread.start()

    def _rollback_worker(
        self,
        root: str,
        mode: str,
        label: str,
        moves: list[tuple[str, str]],
        cancel_event: threading.Event,
        progress_callback: Callable[[int, int], None],
    ) -> None:
        try:
            result = rollback_moves(
                moves,
                root,
                dry_run=False,
                cancel_event=cancel_event,
                progress_callback=progress_callback,
            )
            self.work_queue.put(("rollback_done", (root, mode, label, moves, result)))
        except InterruptedError as exc:
            self.work_queue.put(("cancelled", str(exc) or "Reversao cancelada."))
        except Exception as exc:  # noqa: BLE001 - shown in GUI.
            self.work_queue.put(("error", exc))

    def scan(self) -> None:
        path = self.path_var.get().strip()
        if not path:
            messagebox.showwarning("Arruma Dir", "Escolha um diretorio.")
            return
        self._auto_select_mode_for_path()
        if self._check_current_root() is None:
            return

        self.cancel_event.clear()
        self._set_busy(
            "Gerando previa...",
            indeterminate=True,
            detail="Analisando... nada sera movido.",
        )
        self.next_step_var.set(
            "A previa esta em andamento. Voce pode parar a operacao; nada sera movido nesta etapa."
        )
        self.scan_result = None
        self.project_report = None
        self.active_mode = None
        self.active_root = None
        self._clear_tree(self.plan_tree)
        self._clear_tree(self.duplicate_tree)
        self._clear_charts()
        self.duplicate_rows.clear()
        self._reset_summary()

        workers, hardware_summary = self._get_workers()
        self._append_log(f"Usando perfil de hardware: {hardware_summary}")
        try:
            external_drives = (
                self._parse_external_drives()
                if self.mode_var.get() == MODE_PROJECTS and self.external_var.get() and self.external_drives_var.get().strip()
                else []
            )
        except FileNotFoundError as exc:
            self._finish_busy()
            messagebox.showerror("HD externo invalido", str(exc))
            return

        thread = threading.Thread(
            target=self._scan_worker,
            args=(
                path,
                self.mode_var.get(),
                self.compat_var.get(),
                self.duplicates_var.get(),
                self.full_duplicates_var.get(),
                self.cad_duplicates_var.get(),
                self.external_var.get(),
                external_drives,
                False,
                workers,
                self.cancel_event,
            ),
            daemon=True,
        )
        thread.start()

    def _get_workers(self) -> tuple[int, str]:
        mode = normalize_performance_mode(self.performance_var.get())
        if not mode:
            mode = "balanced"
            self.performance_var.set(mode)
        if self.hardware_profile is None:
            self.hardware_profile = detect_hardware()
        workers = self.hardware_profile.workers_for(mode)
        return workers, self.hardware_profile.summary(mode)

    def _scan_worker(
        self,
        path: str,
        mode: str,
        compat_names: bool,
        include_duplicates: bool,
        full_duplicates: bool,
        include_cad_duplicates: bool,
        external: bool,
        external_drives: list[Path],
        populate_base: bool,
        workers: int,
        cancel_event: threading.Event,
    ) -> None:
        try:
            if mode == MODE_PROJECTS:
                status = (
                    "Popular base: comparando HDs externos com a base..."
                    if populate_base
                    else "Projetos/CAD: analisando estrutura e duplicatas..."
                )
                self.work_queue.put(("status", status))
                result = scan_projects(
                    Path(path),
                    external=external,
                    external_drives=external_drives or None,
                    no_hash=not include_duplicates,
                    max_hash_size_mb=None if full_duplicates else 2048,
                    include_cad_duplicates=include_cad_duplicates,
                    hash_workers=workers,
                    populate_base=populate_base,
                    cancel_event=cancel_event,
                )
                self.work_queue.put(("project_scan_done", result))
                return

            self.work_queue.put(("status", "Documentos/PARA: classificando e procurando repetidos..."))
            result = scan_directory(
                path,
                compat_names=compat_names,
                include_duplicates=include_duplicates,
                include_cad=include_cad_duplicates,
                duplicate_time_limit=None if full_duplicates else 90.0,
                duplicate_max_size_mb=None if full_duplicates else 512,
                hash_workers=workers,
                cancel_event=cancel_event,
            )
            self.work_queue.put(("scan_done", result))

        except InterruptedError:
            self.work_queue.put(("cancelled", "Operacao cancelada pelo usuario."))
        except Exception as exc:  # noqa: BLE001 - shown in GUI.
            self.work_queue.put(("error", exc))

    def standardize_names(self) -> None:
        if self._check_current_root() is None:
            return
        root = Path(self.path_var.get().strip()).expanduser()
        self.cancel_event.clear()
        self._set_busy(
            "Gerando previa de padronizacao de nomes...",
            indeterminate=True,
            detail="Ramtech/Opcao e CAD protegido ficam preservados.",
        )
        self.scan_result = None
        self.project_report = None
        self.active_mode = None
        self.active_root = None
        self.duplicate_rows.clear()
        self._clear_tree(self.plan_tree)
        self._clear_tree(self.duplicate_tree)
        self._clear_charts()
        self._reset_summary()
        self.next_step_var.set("Revise a aba Plano. Se estiver correto, use Aplicar plano para renomear.")
        thread = threading.Thread(
            target=self._standardize_worker,
            args=(str(root), self.cad_duplicates_var.get(), self.cancel_event),
            daemon=True,
        )
        thread.start()

    def _standardize_worker(self, path: str, include_cad: bool, cancel_event: threading.Event) -> None:
        try:
            result = scan_name_standardization(path, include_cad=include_cad, cancel_event=cancel_event)
            self.work_queue.put(("standardization_scan_done", result))
        except InterruptedError as exc:
            self.work_queue.put(("cancelled", str(exc) or "Padronizacao cancelada."))
        except Exception as exc:
            self.work_queue.put(("error", exc))

    def apply_organization(self) -> None:
        if not self._require_same_root():
            return
        if self.active_mode == MODE_PROJECTS:
            if not self.project_report or not self.project_report.organization:
                if self.project_report and self.project_report.external_candidates:
                    messagebox.showinfo("Arruma Dir", "Revise os candidatos externos e use o botao Popular base.")
                else:
                    messagebox.showinfo("Arruma Dir", "Nenhum plano de projetos carregado.")
                return
            count = len(self.project_report.organization)
            if not self._confirm_action(
                "Aplicar organizacao",
                f"Mover {count} item(ns) do plano de projetos agora?\n\n"
                "Nada sera apagado. Destinos ficam dentro da raiz selecionada.",
            ):
                return
            self._set_busy("Aplicando organizacao de projetos...")
            progress_callback = self._create_progress_callback()
            thread = threading.Thread(
                target=self._project_apply_worker,
                args=("organize", None, self.cancel_event, progress_callback),
                daemon=True,
            )
            thread.start()
            return

        if not self.scan_result or not self.scan_result.plan:
            messagebox.showinfo("Arruma Dir", "Nenhum plano carregado.")
            return
        count = len(self.scan_result.plan)
        standardization_plan = all(item.category == "padronizacao/nomes" for item in self.scan_result.plan)
        title = "Aplicar padronizacao" if standardization_plan else "Aplicar organizacao"
        verb = "Padronizar" if standardization_plan else "Mover"
        detail = (
            "Ramtech/Opcao e CAD protegido ja ficaram fora da previa quando detectados."
            if standardization_plan
            else "Nada sera apagado. Destinos ficam dentro da pasta escolhida."
        )
        if not self._confirm_action(
            title,
            f"{verb} {count} item(ns) do plano agora?\n\n{detail}",
        ):
            return
        self._set_busy("Aplicando padronizacao..." if standardization_plan else "Aplicando organizacao...")
        progress_callback = self._create_progress_callback()
        thread = threading.Thread(target=self._apply_worker, args=(self.cancel_event, progress_callback), daemon=True)
        thread.start()

    def populate_base(self) -> None:
        if self.mode_var.get() != MODE_PROJECTS:
            messagebox.showinfo("Arruma Dir", "Popular base esta disponivel no modo Projetos/CAD.")
            return

        if self.project_report and self.active_mode == MODE_PROJECTS:
            candidates = [item for item in self.project_report.external_candidates if item.decision == "popular_base"]
            if candidates:
                if not self._require_same_root():
                    return
                count = len(candidates)
                if not self._confirm_action(
                    "Popular base",
                    f"Copiar {count} item(ns) ausente(s) dos HDs externos para a base de projetos?\n\n"
                    "Nada sera removido dos HDs externos. Arquivos ja existentes por conteudo foram ignorados na previa.",
                    code="POPULAR",
                ):
                    return
                self._set_busy("Popular base: copiando itens ausentes...")
                progress_callback = self._create_progress_callback()
                thread = threading.Thread(
                    target=self._project_apply_worker,
                    args=("populate_base", None, self.cancel_event, progress_callback),
                    daemon=True,
                )
                thread.start()
                return

        path = self.path_var.get().strip()
        if not path:
            messagebox.showwarning("Arruma Dir", "Escolha a raiz da base de projetos.")
            return
        self.mode_var.set(MODE_PROJECTS)
        self._update_mode_controls()
        if self._check_current_root() is None:
            return
        try:
            external_drives = self._parse_external_drives()
        except FileNotFoundError as exc:
            messagebox.showerror("HD externo invalido", str(exc))
            return
        if not external_drives:
            messagebox.showinfo("Arruma Dir", "Selecione pelo menos um HD ou pasta externa para popular a base.")
            return

        self.external_var.set(True)
        self.cancel_event.clear()
        self._set_busy(
            "Popular base: vasculhando HDs externos...",
            indeterminate=True,
            detail="Comparando com a base por conteudo.",
        )
        self.scan_result = None
        self.project_report = None
        self.active_mode = None
        self.active_root = None
        self._clear_tree(self.plan_tree)
        self._clear_tree(self.duplicate_tree)
        self._clear_charts()
        self.duplicate_rows.clear()
        self._reset_summary()
        self.next_step_var.set("Popular base esta gerando uma previa. Revise o Plano antes de copiar.")

        workers, hardware_summary = self._get_workers()
        self._append_log(f"Usando perfil de hardware: {hardware_summary}")
        thread = threading.Thread(
            target=self._scan_worker,
            args=(
                path,
                MODE_PROJECTS,
                False,
                False,
                False,
                False,
                True,
                external_drives,
                True,
                workers,
                self.cancel_event,
            ),
            daemon=True,
        )
        thread.start()

    def _apply_worker(self, cancel_event: threading.Event, progress_callback: Callable[[int, int], None]) -> None:
        try:
            assert self.scan_result is not None
            result = apply_plan(
                self.scan_result.plan,
                self.scan_result.root,
                dry_run=False,
                cancel_event=cancel_event,
                progress_callback=progress_callback,
            )
            self.work_queue.put(("apply_done", result))
        except InterruptedError as exc:
            self.work_queue.put(("cancelled", str(exc) or "Aplicacao cancelada."))
        except Exception as exc:
            self.work_queue.put(("error", exc))

    def move_duplicates(self) -> None:
        if not self._require_same_root():
            return
        if self.active_mode == MODE_PROJECTS:
            if not self.project_report or not self.project_report.duplicates:
                messagebox.showinfo("Arruma Dir", "Nenhum repetido carregado.")
                return
            count = len(self.project_report.duplicates)
            if not self._confirm_action(
                "Mover duplicatas",
                f"Mover {count} duplicata(s) exata(s) para a quarentena _arruma_projetos?\n\n"
                "Arquivos CAD so entram aqui se voce marcou a opcao de incluir duplicatas CAD. "
                "Possiveis duplicatas ficam no lugar.",
            ):
                return
            self._set_busy("Movendo duplicatas de projetos...")
            progress_callback = self._create_progress_callback()
            thread = threading.Thread(
                target=self._project_apply_worker,
                args=("duplicates", None, self.cancel_event, progress_callback),
                daemon=True,
            )
            thread.start()
            return

        if not self.scan_result or not self.scan_result.duplicates:
            messagebox.showinfo("Arruma Dir", "Nenhum repetido carregado.")
            return
        if not self._confirm_action(
            "Mover duplicatas",
            "Mover somente copias exatamente iguais com marcador de copia para _duplicados?\n\n"
            "Possiveis duplicatas, itens sem hash e arquivos sem marcador claro ficam no lugar para decisao manual.",
        ):
            return
        self._set_busy("Movendo repetidos...")
        progress_callback = self._create_progress_callback()
        thread = threading.Thread(target=self._dedupe_worker, args=(self.cancel_event, progress_callback), daemon=True)
        thread.start()

    def _dedupe_worker(self, cancel_event: threading.Event, progress_callback: Callable[[int, int], None]) -> None:
        try:
            assert self.scan_result is not None
            result = move_duplicates_to_quarantine(
                self.scan_result.root,
                self.scan_result.duplicates,
                dry_run=False,
                cancel_event=cancel_event,
                progress_callback=progress_callback,
            )
            self.work_queue.put(("dedupe_done", result))
        except InterruptedError as exc:
            self.work_queue.put(("cancelled", str(exc) or "Movimentacao de duplicatas cancelada."))
        except Exception as exc:
            self.work_queue.put(("error", exc))

    def move_selected_duplicate(self) -> None:
        if not self._require_same_root():
            return
        selected = self.duplicate_tree.selection()
        if not selected:
            messagebox.showinfo("Arruma Dir", "Selecione um item na aba Repetidos.")
            return
        row = self.duplicate_rows.get(selected[0])
        if not row:
            messagebox.showinfo("Arruma Dir", "Item selecionado invalido.")
            return

        if row.get("mode") == MODE_PROJECTS:
            operation = row.get("operation")
            if not isinstance(operation, DuplicateOperation) or not self.project_report:
                messagebox.showinfo("Arruma Dir", "Item selecionado invalido.")
                return
            if not self._confirm_action(
                "Mover selecionado",
                f"Mover este arquivo para a quarentena?\n\n{operation.source}\n\nGuardando principal:\n{operation.keeper}",
                code="MOVER",
            ):
                return
            self._set_busy("Movendo duplicata selecionada...")
            progress_callback = self._create_progress_callback()
            thread = threading.Thread(
                target=self._project_apply_worker,
                args=("selected_duplicate", operation, self.cancel_event, progress_callback),
                daemon=True,
            )
            thread.start()
            return

        if not self.scan_result:
            messagebox.showinfo("Arruma Dir", "Item selecionado invalido.")
            return

        file_path = str(row["file"])
        role = str(row["role"])
        kind = str(row["kind"])
        differences = str(row.get("differences") or "")

        if kind == "exact" and role == "principal":
            messagebox.showinfo("Arruma Dir", "Este e o arquivo principal do grupo exato.")
            return

        if kind == "possible":
            message = (
                "Este arquivo tem diferencas e sera mantido por padrao.\n\n"
                f"{differences}\n\nMover mesmo assim?"
            )
        else:
            message = "Mover este arquivo para _duplicados?"
        if not self._confirm_action("Mover selecionado", message, code="MOVER"):
            return

        self._set_busy("Movendo item selecionado...")
        progress_callback = self._create_progress_callback()
        thread = threading.Thread(
            target=self._move_selected_worker, args=(file_path, kind, self.cancel_event, progress_callback), daemon=True
        )
        thread.start()

    def _move_selected_worker(
        self, file_path: str, kind: str, cancel_event: threading.Event, progress_callback: Callable[[int, int], None]
    ) -> None:
        try:
            assert self.scan_result is not None
            bucket = "decisao_manual" if kind == "possible" else "duplicado_exato"
            result = move_files_to_quarantine(
                self.scan_result.root,
                [file_path],
                bucket=bucket,
                dry_run=False,
                cancel_event=cancel_event,
                progress_callback=progress_callback,
            )
            self.work_queue.put(("selected_duplicate_done", result))
        except InterruptedError as exc:
            self.work_queue.put(("cancelled", str(exc) or "Movimentacao cancelada."))
        except Exception as exc:
            self.work_queue.put(("error", exc))

    def _project_apply_worker(
        self, action: str, operation: DuplicateOperation | None, cancel_event: threading.Event, progress_callback: Callable
    ) -> None:
        try:
            assert self.project_report is not None
            if action == "selected_duplicate" and operation is not None:
                report = ProjectReport(
                    root=self.project_report.root,
                    generated_at=self.project_report.generated_at,
                    duplicates=[operation],
                )
                result = apply_project_report(
                    report,
                    organize=False,
                    duplicates=True,
                    import_external=False,
                    yes=True,
                    cancel_event=cancel_event,
                    progress_callback=progress_callback,
                )
            elif action == "populate_base":
                report = ProjectReport(
                    root=self.project_report.root,
                    generated_at=self.project_report.generated_at,
                    external_candidates=[
                        item for item in self.project_report.external_candidates if item.decision == "popular_base"
                    ],
                )
                result = apply_project_report(
                    report,
                    organize=False,
                    duplicates=False,
                    import_external=True,
                    yes=True,
                    cancel_event=cancel_event,
                    progress_callback=progress_callback,
                )
            else:
                result = apply_project_report(
                    self.project_report,
                    organize=action == "organize",
                    duplicates=action == "duplicates",
                    import_external=False,
                    yes=True,
                    cancel_event=cancel_event,
                    progress_callback=progress_callback,
                )
            self.work_queue.put(("project_apply_done", result))
        except InterruptedError as exc:
            self.work_queue.put(("cancelled", str(exc) or "Operacao de projetos cancelada."))
        except Exception as exc:
            self.work_queue.put(("error", exc))

    def export_json(self) -> None:
        if self.active_mode == MODE_PROJECTS:
            if not self.project_report:
                messagebox.showinfo("Arruma Dir", "Escaneie antes de exportar.")
                return
            initial_dir = state_path(Path(self.project_report.root), REPORTS_DIR)
            selected = filedialog.asksaveasfilename(
                initialfile="projetos-report.json",
                initialdir=str(initial_dir),
                defaultextension=".json",
                filetypes=(("JSON", "*.json"), ("Todos", "*.*")),
            )
            if selected:
                target = Path(selected)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(self.project_report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
                self._append_log(f"JSON salvo em {target}")
            return

        if not self.scan_result:
            messagebox.showinfo("Arruma Dir", "Escaneie antes de exportar.")
            return
        initial = Path(self.scan_result.root) / "_arruma_dir" / "plano.arruma-plan.json"
        selected = filedialog.asksaveasfilename(
            initialfile=initial.name,
            initialdir=str(initial.parent),
            defaultextension=".json",
            filetypes=(("JSON", "*.json"), ("Todos", "*.*")),
        )
        if selected:
            target = write_scan_json(self.scan_result, selected)
            self._append_log(f"JSON salvo em {target}")

    def _poll_queue(self) -> None:
        try:
            while True:
                event, payload = self.work_queue.get_nowait()
                if event == "scan_done":
                    self._on_scan_done(payload)  # type: ignore[arg-type]
                elif event == "standardization_scan_done":
                    self._on_standardization_scan_done(payload)  # type: ignore[arg-type]
                elif event == "project_scan_done":
                    self._on_project_scan_done(payload)  # type: ignore[arg-type]
                elif event in {"apply_done", "dedupe_done", "selected_duplicate_done"}:
                    self._on_apply_done(payload, event)  # type: ignore[arg-type]
                elif event == "project_apply_done":
                    self._on_project_apply_done(payload)  # type: ignore[arg-type]
                elif event == "rollback_done":
                    self._on_rollback_done(payload)  # type: ignore[arg-type]
                elif event == "progress":
                    self._on_progress(payload)  # type: ignore[arg-type]
                elif event == "status":
                    self._on_status(payload)  # type: ignore[arg-type]
                elif event == "cancelled":
                    self._on_cancelled(payload)  # type: ignore[arg-type]
                elif event == "error":
                    self._on_error(payload)  # type: ignore[arg-type]
        except queue.Empty:
            pass
        self.after(120, self._poll_queue)

    def _on_status(self, message: str) -> None:
        self.status_var.set(message)
        self.progress_text_var.set(message)
        self._append_log(message)

    def _on_progress(self, payload: tuple[int, int]) -> None:
        current, total = payload
        if total > 0:
            if self.progress_is_indeterminate:
                self.progress_bar.stop()
                self.progress_bar.configure(mode="determinate")
                self.progress_is_indeterminate = False
            percent = (current / total) * 100
            self.progress_var.set(percent)
            self.progress_text_var.set(f"{current} de {total}")
        else:
            self.progress_var.set(0.0)
            self.progress_text_var.set("")

    def _on_scan_done(self, result: ScanResult) -> None:
        self.scan_result = result
        self.project_report = None
        self.active_mode = MODE_DOCUMENTS
        self.active_root = result.root
        self.duplicate_rows.clear()
        self._clear_tree(self.plan_tree)
        self._clear_tree(self.duplicate_tree)
        for item in result.plan:
            self.plan_tree.insert(
                "",
                "end",
                values=(item.action, item.category, item.source, item.destination, item.reason),
            )
        for group in result.duplicates:
            keeper = choose_duplicate_keeper(group.files, result.root) if group.kind == "exact" else ""
            differences = "; ".join(group.differences) if group.differences else group.reason
            if group.kind == "exact" and not is_batch_safe_duplicate_group(group):
                differences = f"{differences}; decisao manual"
            for file_path in group.files:
                marker = "principal" if file_path == keeper else ("repetido" if group.kind == "exact" else "revisar")
                item_id = self.duplicate_tree.insert(
                    "",
                    "end",
                    values=(
                        group.kind,
                        group.size if group.size else "varios",
                        duplicate_hash_label(group),
                        f"{marker}: {file_path}",
                        differences,
                    ),
                )
                self.duplicate_rows[item_id] = {
                    "mode": MODE_DOCUMENTS,
                    "file": file_path,
                    "kind": group.kind,
                    "role": marker,
                    "differences": differences,
                }
        stats = result.stats
        self.status_var.set(
            f"{stats['planned_moves']} movimentos, "
            f"{stats['batch_safe_duplicate_groups']} copias exatas, "
            f"{stats['exact_duplicate_groups']} exatos totais, "
            f"{stats['possible_duplicate_groups']} possiveis, "
            f"{stats['errors']} erros"
        )
        self._set_summary(
            planned=stats["planned_moves"],
            duplicates=stats["exact_duplicate_groups"],
            possible=stats["possible_duplicate_groups"],
            external=0,
            errors=stats["errors"],
            next_step=self._document_scan_next_step(stats),
        )
        self._append_log(f"Previa concluida: {result.root}")
        for skipped in result.skipped:
            self._append_log(f"Aviso: {skipped}")
        for error in result.errors:
            self._append_log(f"Erro: {error}")
        self._write_document_scan_log(result)
        self._update_pie_chart(result.file_summary)
        self._update_directory_chart(result.directory_summary)
        self._finish_busy()

    def _on_standardization_scan_done(self, result: ScanResult) -> None:
        self._on_scan_done(result)
        stats = result.stats
        self.status_var.set(f"Padronizacao: {stats['planned_moves']} renomeacao(oes), {stats['errors']} erros")
        if stats["planned_moves"]:
            self.next_step_var.set("Revise a aba Plano. Use Aplicar plano para renomear os itens listados.")
        else:
            self.next_step_var.set("Nenhum nome fora do padrao encontrado fora das areas preservadas.")
        self._append_log("Previa de padronizacao concluida. Ramtech/Opcao foram preservados quando detectados.")

    def _on_project_scan_done(self, report: ProjectReport) -> None:
        self.project_report = report
        self.scan_result = None
        self.active_mode = MODE_PROJECTS
        self.active_root = report.root
        self.duplicate_rows.clear()
        self._clear_tree(self.plan_tree)
        self._clear_tree(self.duplicate_tree)

        for item in report.organization:
            self.plan_tree.insert(
                "",
                "end",
                values=(item.action, "Projetos/CAD", item.source, item.destination, item.reason),
            )
        for item in report.external_candidates:
            self.plan_tree.insert(
                "",
                "end",
                values=(
                    item.decision,
                    "Popular base" if item.decision == "popular_base" else "HD externo",
                    item.source,
                    item.destination,
                    f"score {item.score}: {', '.join(item.reasons)}",
                ),
            )
        for item in report.duplicates:
            item_id = self.duplicate_tree.insert(
                "",
                "end",
                values=(
                    "exact",
                    item.size,
                    item.sha256[:12],
                    f"repetido: {item.source}",
                    f"principal: {item.keeper}; {item.reason}",
                ),
            )
            self.duplicate_rows[item_id] = {
                "mode": MODE_PROJECTS,
                "file": item.source,
                "kind": "exact",
                "role": "repetido",
                "operation": item,
            }

        stats = report.stats
        self.status_var.set(
            f"{stats['organization_moves']} movimentos, "
            f"{stats['duplicate_moves']} duplicatas, "
            f"{stats['external_candidates']} candidatos externos, "
            f"{stats['errors']} erros"
        )
        self._set_summary(
            planned=stats["organization_moves"],
            duplicates=stats["duplicate_moves"],
            possible=0,
            external=stats["external_candidates"],
            errors=stats["errors"],
            next_step=self._project_scan_next_step(stats),
        )
        self._append_log(f"Previa de projetos concluida: {report.root}")
        for warning in report.warnings:
            self._append_log(f"Aviso: {warning}")
        for error in report.errors:
            self._append_log(f"Erro: {error}")
        self._write_project_scan_log(report)
        self._update_pie_chart(report.file_summary)
        self._update_directory_chart(report.directory_summary)
        self._finish_busy()

    def _on_apply_done(self, result: ApplyResult, event: str) -> None:
        labels = {
            "apply_done": "Organizacao",
            "dedupe_done": "Repetidos exatos",
            "selected_duplicate_done": "Item selecionado",
        }
        label = labels.get(event, "Acao")
        if event == "apply_done" and self.scan_result and all(
            item.category == "padronizacao/nomes" for item in self.scan_result.plan
        ):
            label = "Padronizacao"
        self.status_var.set(f"{label}: {len(result.moved)} movimentos, {len(result.errors)} erros")
        self.next_step_var.set("Acao concluida. Gere uma nova previa para validar o estado atual da pasta.")
        self._append_log(f"{label}: {len(result.moved)} movimentos")
        for source, destination in result.moved[:80]:
            self._append_log(f"{source} -> {destination}")
        for skipped in result.skipped:
            self._append_log(f"Ignorado: {skipped}")
        for error in result.errors:
            self._append_log(f"Erro: {error}")
        self._write_document_apply_log(result, label)
        if result.moved and self.active_root:
            self._remember_rollback(root=self.active_root, mode=MODE_DOCUMENTS, label=label, moves=result.moved)
        else:
            self._clear_rollback()
        self._finish_busy()

    def _on_project_apply_done(self, result: ProjectApplyResult) -> None:
        moved = result.get("moved", [])
        copied = result.get("copied", [])
        errors = result.get("errors", [])
        skipped = result.get("skipped", [])
        move_pairs = list(result.get("moved_pairs", []))
        self.status_var.set(f"Projetos: {len(moved)} movimentos, {len(copied)} copias, {len(errors)} erros")
        self.next_step_var.set("Acao de Projetos/CAD concluida. Gere nova previa antes de aplicar outro lote.")
        self._append_log(f"Projetos: {len(moved)} movimentos, {len(copied)} copias")
        for item in moved[:80]:
            self._append_log(item)
        for item in copied[:80]:
            self._append_log(item)
        for item in skipped:
            self._append_log(f"Ignorado: {item}")
        for item in errors:
            self._append_log(f"Erro: {item}")
        self._write_project_apply_log(result)
        if move_pairs and self.active_root:
            self._remember_rollback(root=self.active_root, mode=MODE_PROJECTS, label="Projetos/CAD", moves=move_pairs)
        else:
            self._clear_rollback()
        self._finish_busy()

    def _on_rollback_done(self, payload: tuple[str, str, str, list[tuple[str, str]], ApplyResult]) -> None:
        root, mode, label, moves, result = payload
        self.status_var.set(f"Reversao de {label}: {len(result.moved)} movimentos, {len(result.errors)} erros")
        self._append_log(f"Reversao de {label}: {len(result.moved)} movimentos")
        for source, destination in result.moved[:80]:
            self._append_log(f"{source} -> {destination}")
        for skipped in result.skipped:
            self._append_log(f"Ignorado: {skipped}")
        for error in result.errors:
            self._append_log(f"Erro: {error}")
        self._write_rollback_log(root, mode, label, result)

        remaining = [(original, current) for original, current in moves if Path(current).exists()]
        if remaining and (result.errors or result.skipped):
            self._remember_rollback(root=root, mode=mode, label=label, moves=remaining)
            self.next_step_var.set(
                "Reversao parcial. Corrija os itens do log e use Voltar ultima acao para tentar o restante."
            )
        else:
            self._clear_rollback()
            self.next_step_var.set("Reversao concluida. Gere uma nova previa para validar o estado atual da pasta.")
        self._finish_busy()

    def _write_document_scan_log(self, result: ScanResult) -> None:
        logger, log_path = create_operation_logger(result.root, mode=MODE_DOCUMENTS, operation="gui-scan")
        try:
            logger.info("interface=gui modo=Documentos/PARA raiz=%s gerado_em=%s", result.root, result.generated_at)
            for key, value in result.stats.items():
                logger.info("stat.%s=%s", key, value)
            for index, item in enumerate(result.plan, start=1):
                logger.info(
                    "plano[%04d] action=%s category=%s source=%s destination=%s reason=%s is_directory=%s size=%s",
                    index,
                    item.action,
                    item.category,
                    item.source,
                    item.destination,
                    item.reason,
                    item.is_directory,
                    item.size,
                )
            for index, group in enumerate(result.duplicates, start=1):
                logger.info(
                    "duplicata[%04d] kind=%s size=%s sha256=%s reason=%s differences=%s files=%s",
                    index,
                    group.kind,
                    group.size,
                    group.sha256,
                    group.reason,
                    "; ".join(group.differences),
                    " | ".join(group.files),
                )
            for item in result.skipped:
                logger.warning("%s", item)
            for item in result.errors:
                logger.error("%s", item)
        finally:
            close_logger(logger)
        self._append_log(f"Log completo: {log_path}")

    def _write_project_scan_log(self, report: ProjectReport) -> None:
        logger, log_path = create_operation_logger(report.root, mode=MODE_PROJECTS, operation="gui-project-scan")
        try:
            logger.info(
                format_log_event(
                    "project_report.generated",
                    interface="gui",
                    mode="Projetos/CAD",
                    root=report.root,
                    generated_at=report.generated_at,
                )
            )
            for key, value in report.stats.items():
                logger.info(format_log_event("project_report.stat", name=key, value=value))
            for index, item in enumerate(report.organization, start=1):
                logger.info(
                    format_log_event(
                        "project.organization",
                        index=index,
                        action=item.action,
                        source=item.source,
                        destination=item.destination,
                        reason=item.reason,
                    )
                )
            for index, item in enumerate(report.duplicates, start=1):
                logger.info(
                    format_log_event(
                        "project.duplicate",
                        index=index,
                        size=item.size,
                        sha256=item.sha256,
                        source=item.source,
                        keeper=item.keeper,
                        remove=item.source,
                        destination=item.destination,
                        reason=item.reason,
                    )
                )
            for index, item in enumerate(report.external_candidates, start=1):
                logger.info(
                    format_log_event(
                        "project.external_candidate",
                        index=index,
                        score=item.score,
                        drive=item.drive,
                        source=item.source,
                        destination=item.destination,
                        reasons=item.reasons,
                        size=item.size,
                        sha256=item.sha256,
                        duplicate_of=item.duplicate_of,
                        decision=item.decision,
                    )
                )
            for item in report.warnings:
                logger.warning(format_log_event("project.warning", message=item))
            for item in report.errors:
                logger.error(format_log_event("project.error", message=item))
        finally:
            close_logger(logger)
        self._append_log(f"Log completo: {log_path}")

    def _write_document_apply_log(self, result: ApplyResult, label: str) -> None:
        if not self.active_root:
            return
        logger, log_path = create_operation_logger(self.active_root, mode=MODE_DOCUMENTS, operation="gui-apply")
        try:
            logger.info("interface=gui acao=%s movimentos=%s ignorados=%s erros=%s", label, len(result.moved), len(result.skipped), len(result.errors))
            for source, destination in result.moved:
                logger.info("move source=%s destination=%s", source, destination)
            for item in result.skipped:
                logger.warning("%s", item)
            for item in result.errors:
                logger.error("%s", item)
        finally:
            close_logger(logger)
        self._append_log(f"Log completo: {log_path}")

    def _write_project_apply_log(self, result: ProjectApplyResult) -> None:
        if not self.active_root:
            return
        logger, log_path = create_operation_logger(self.active_root, mode=MODE_PROJECTS, operation="gui-project-apply")
        try:
            logger.info(
                format_log_event(
                    "project_apply.summary",
                    interface="gui",
                    action="Projetos",
                    moved=len(result.get("moved", [])),
                    copied=len(result.get("copied", [])),
                    skipped=len(result.get("skipped", [])),
                    errors=len(result.get("errors", [])),
                )
            )
            for item in result.get("moved", []):
                logger.info(format_log_event("project_apply.item", kind="moved", value=item))
            for item in result.get("copied", []):
                logger.info(format_log_event("project_apply.item", kind="copied", value=item))
            for item in result.get("skipped", []):
                logger.warning(format_log_event("project_apply.skipped", message=item))
            for item in result.get("errors", []):
                logger.error(format_log_event("project_apply.error", message=item))
        finally:
            close_logger(logger)
        self._append_log(f"Log completo: {log_path}")

    def _write_rollback_log(self, root: str, mode: str, label: str, result: ApplyResult) -> None:
        logger, log_path = create_operation_logger(root, mode=mode, operation="gui-rollback")
        try:
            logger.info(
                "interface=gui acao=reversao label=%s movimentos=%s ignorados=%s erros=%s",
                label,
                len(result.moved),
                len(result.skipped),
                len(result.errors),
            )
            for source, destination in result.moved:
                logger.info("rollback source=%s destination=%s", source, destination)
            for item in result.skipped:
                logger.warning("%s", item)
            for item in result.errors:
                logger.error("%s", item)
        finally:
            close_logger(logger)
        self._append_log(f"Log completo: {log_path}")

    def _on_error(self, exc: object) -> None:
        self.status_var.set("Erro")
        messagebox.showerror("Arruma Dir", str(exc))
        self._append_log(f"Erro: {exc}")
        self._finish_busy()

    def _on_cancelled(self, message: str) -> None:
        self.status_var.set(message or "Operacao cancelada.")
        self._append_log(message or "Operacao cancelada.")
        self._finish_busy()

    def _clear_tree(self, tree: ttk.Treeview) -> None:
        for item in tree.get_children():
            tree.delete(item)

    def _set_busy(self, message: str, *, indeterminate: bool = False, detail: str = "") -> None:
        self.busy = True
        self.status_var.set(message)
        self._append_log(message)
        self.progress_var.set(0.0)
        self.progress_text_var.set(detail)
        self.progress_frame.grid()
        self.progress_bar.stop()
        self.progress_bar.configure(mode="indeterminate" if indeterminate else "determinate")
        self.progress_is_indeterminate = indeterminate
        if indeterminate:
            self.progress_bar.start(12)
        self.cancel_event.clear()
        self.stop_button.grid()
        self._set_action_buttons()

    def _finish_busy(self) -> None:
        self.busy = False
        self.progress_bar.stop()
        self.progress_bar.configure(mode="determinate")
        self.progress_is_indeterminate = False
        self.progress_frame.grid_remove()
        self.progress_var.set(0.0)
        self.progress_text_var.set("")
        self.stop_button.grid_remove()
        self.cancel_event.clear()
        self._set_action_buttons()

    def _append_log(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")


def run() -> None:
    app = ArrumaDirApp()
    app.mainloop()
