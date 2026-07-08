from __future__ import annotations

import json
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from .logging_utils import close_logger, create_operation_logger
from .organizer import (
    ApplyResult,
    ScanResult,
    apply_plan,
    choose_duplicate_keeper,
    default_documents_path,
    is_batch_safe_duplicate_group,
    move_duplicates_to_quarantine,
    move_files_to_quarantine,
    scan_directory,
    write_scan_json,
)
from .project_organizer import (
    DEFAULT_ROOT as DEFAULT_PROJECTS_ROOT,
    REPORTS_DIR,
    DuplicateOperation,
    ProjectReport,
    apply_report as apply_project_report,
    scan_projects,
    state_path,
)
from .safety import SafetyCheck, check_organization_root


MODE_DOCUMENTS = "documents"
MODE_PROJECTS = "projects"


class ArrumaDirApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Arruma Dir")
        self.minsize(1120, 700)
        self.scan_result: ScanResult | None = None
        self.project_report: ProjectReport | None = None
        self.active_mode: str | None = None
        self.active_root: str | None = None
        self.duplicate_rows: dict[str, dict[str, object]] = {}
        self.work_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.busy = False

        self.mode_var = tk.StringVar(value=MODE_DOCUMENTS)
        self.path_var = tk.StringVar(value=str(default_documents_path()))
        self.compat_var = tk.BooleanVar(value=False)
        self.duplicates_var = tk.BooleanVar(value=True)
        self.full_duplicates_var = tk.BooleanVar(value=False)
        self.cad_duplicates_var = tk.BooleanVar(value=False)
        self.external_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Pronto")
        self.safety_var = tk.StringVar(value="Escolha o local, gere uma previa e revise antes de aplicar.")

        self._build_layout()
        self._update_mode_controls()
        self._set_action_buttons()
        self.after(120, self._poll_queue)

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        top = ttk.Frame(self, padding=(12, 12, 12, 8))
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="Modo").grid(row=0, column=0, sticky="w", padx=(0, 8))
        mode_box = ttk.Frame(top)
        mode_box.grid(row=0, column=1, columnspan=2, sticky="w")
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

        ttk.Label(top, text="Local").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
        path_entry = ttk.Entry(top, textvariable=self.path_var)
        path_entry.grid(row=1, column=1, sticky="ew", pady=(8, 0))
        ttk.Button(top, text="Escolher", command=self.choose_directory).grid(row=1, column=2, padx=(8, 0), pady=(8, 0))

        safety = ttk.Frame(self, padding=(12, 0, 12, 8))
        safety.grid(row=1, column=0, sticky="ew")
        safety.columnconfigure(0, weight=1)
        ttk.Label(safety, textvariable=self.safety_var, foreground="#5b4b00").grid(row=0, column=0, sticky="w")

        options = ttk.Frame(self, padding=(12, 0, 12, 8))
        options.grid(row=2, column=0, sticky="ew")
        options.columnconfigure(5, weight=1)

        self.compat_check = ttk.Checkbutton(options, text="Nomes compativeis", variable=self.compat_var)
        self.compat_check.grid(row=0, column=0, sticky="w")
        self.duplicates_check = ttk.Checkbutton(options, text="Buscar repetidos", variable=self.duplicates_var)
        self.duplicates_check.grid(row=0, column=1, sticky="w", padx=(18, 0))
        self.full_duplicates_check = ttk.Checkbutton(
            options,
            text="Duplicatas completas (lento)",
            variable=self.full_duplicates_var,
        )
        self.full_duplicates_check.grid(row=0, column=2, sticky="w", padx=(18, 0))
        self.cad_duplicates_check = ttk.Checkbutton(
            options,
            text="Incluir duplicatas CAD",
            variable=self.cad_duplicates_var,
        )
        self.cad_duplicates_check.grid(row=0, column=3, sticky="w", padx=(18, 0))
        self.external_check = ttk.Checkbutton(options, text="Vasculhar HDs externos", variable=self.external_var)
        self.external_check.grid(row=0, column=4, sticky="w", padx=(18, 0))

        self.scan_button = ttk.Button(options, text="Gerar previa", command=self.scan)
        self.scan_button.grid(row=0, column=6, sticky="e")
        self.export_button = ttk.Button(options, text="Exportar JSON", command=self.export_json)
        self.export_button.grid(row=0, column=7, sticky="e", padx=(8, 0))
        self.move_selected_button = ttk.Button(options, text="Mover selecionado", command=self.move_selected_duplicate)
        self.move_selected_button.grid(row=0, column=8, sticky="e", padx=(8, 0))
        self.move_duplicates_button = ttk.Button(options, text="Mover duplicatas", command=self.move_duplicates)
        self.move_duplicates_button.grid(row=0, column=9, sticky="e", padx=(8, 0))
        self.apply_button = ttk.Button(options, text="Aplicar organizacao", command=self.apply_organization)
        self.apply_button.grid(row=0, column=10, sticky="e", padx=(8, 0))

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

        self.log = tk.Text(notebook, height=8, wrap="word")
        self.log.configure(state="disabled")
        notebook.add(self.log, text="Log")

        status = ttk.Frame(self, padding=(12, 0, 12, 12))
        status.grid(row=4, column=0, sticky="ew")
        status.columnconfigure(0, weight=1)
        ttk.Label(status, textvariable=self.status_var).grid(row=0, column=0, sticky="w")

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
        self.duplicate_rows.clear()
        self._update_mode_controls()
        self._set_action_buttons()
        self.status_var.set("Pronto")

    def _update_mode_controls(self) -> None:
        if self.mode_var.get() == MODE_PROJECTS:
            self.compat_check.configure(state="disabled")
            self.full_duplicates_check.configure(state="normal")
            self.cad_duplicates_check.configure(state="normal")
            self.external_check.configure(state="normal")
            self.safety_var.set("Projetos/CAD: arvores SolidWorks, Electrical, EPLAN e AutoCAD sao preservadas por padrao.")
        else:
            self.compat_check.configure(state="normal")
            self.full_duplicates_check.configure(state="normal")
            self.cad_duplicates_check.configure(state="disabled")
            self.external_check.configure(state="disabled")
            self.safety_var.set("Documentos/PARA: gere uma previa, revise destinos e aplique somente com confirmacao.")

    def _set_action_buttons(self) -> None:
        has_document_scan = self.scan_result is not None and self.active_mode == MODE_DOCUMENTS
        has_project_scan = self.project_report is not None and self.active_mode == MODE_PROJECTS
        has_scan = has_document_scan or has_project_scan
        has_duplicates = bool(
            (self.scan_result and self.scan_result.duplicates)
            or (self.project_report and self.project_report.duplicates)
        )
        normal = "normal"
        disabled = "disabled"
        self.scan_button.configure(state=disabled if self.busy else normal)
        self.export_button.configure(state=normal if has_scan and not self.busy else disabled)
        self.apply_button.configure(state=normal if has_scan and not self.busy else disabled)
        self.move_duplicates_button.configure(state=normal if has_duplicates and not self.busy else disabled)
        self.move_selected_button.configure(state=normal if has_duplicates and not self.busy else disabled)

    def choose_directory(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.path_var.get() or str(Path.home()))
        if selected:
            self.path_var.set(selected)
            self._auto_select_mode_for_path()

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

    def scan(self) -> None:
        path = self.path_var.get().strip()
        if not path:
            messagebox.showwarning("Arruma Dir", "Escolha um diretorio.")
            return
        self._auto_select_mode_for_path()
        if self._check_current_root() is None:
            return

        self._set_busy("Gerando previa...")
        self.scan_result = None
        self.project_report = None
        self.active_mode = None
        self.active_root = None
        self._clear_tree(self.plan_tree)
        self._clear_tree(self.duplicate_tree)
        self.duplicate_rows.clear()

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
            ),
            daemon=True,
        )
        thread.start()

    def _scan_worker(
        self,
        path: str,
        mode: str,
        compat_names: bool,
        include_duplicates: bool,
        full_duplicates: bool,
        include_cad_duplicates: bool,
        external: bool,
    ) -> None:
        try:
            if mode == MODE_PROJECTS:
                result = scan_projects(
                    Path(path),
                    external=external,
                    no_hash=not include_duplicates,
                    max_hash_size_mb=None if full_duplicates else 2048,
                    include_cad_duplicates=include_cad_duplicates,
                )
                self.work_queue.put(("project_scan_done", result))
                return

            result = scan_directory(
                path,
                compat_names=compat_names,
                include_duplicates=include_duplicates,
                duplicate_time_limit=None if full_duplicates else 90.0,
                duplicate_max_size_mb=None if full_duplicates else 512,
            )
            self.work_queue.put(("scan_done", result))
        except Exception as exc:  # noqa: BLE001 - shown in GUI.
            self.work_queue.put(("error", exc))

    def apply_organization(self) -> None:
        if not self._require_same_root():
            return
        if self.active_mode == MODE_PROJECTS:
            if not self.project_report or not self.project_report.organization:
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
            thread = threading.Thread(target=self._project_apply_worker, args=("organize", None), daemon=True)
            thread.start()
            return

        if not self.scan_result or not self.scan_result.plan:
            messagebox.showinfo("Arruma Dir", "Nenhum plano carregado.")
            return
        count = len(self.scan_result.plan)
        if not self._confirm_action(
            "Aplicar organizacao",
            f"Mover {count} item(ns) do plano agora?\n\nNada sera apagado. Destinos ficam dentro da pasta escolhida.",
        ):
            return
        self._set_busy("Aplicando organizacao...")
        thread = threading.Thread(target=self._apply_worker, daemon=True)
        thread.start()

    def _apply_worker(self) -> None:
        assert self.scan_result is not None
        result = apply_plan(self.scan_result.plan, self.scan_result.root, dry_run=False)
        self.work_queue.put(("apply_done", result))

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
                "Arquivos CAD so aparecem aqui se voce marcou a opcao de incluir duplicatas CAD.",
            ):
                return
            self._set_busy("Movendo duplicatas de projetos...")
            thread = threading.Thread(target=self._project_apply_worker, args=("duplicates", None), daemon=True)
            thread.start()
            return

        if not self.scan_result or not self.scan_result.duplicates:
            messagebox.showinfo("Arruma Dir", "Nenhum repetido carregado.")
            return
        if not self._confirm_action(
            "Mover duplicatas",
            "Mover somente copias exatamente iguais com marcador de copia para _duplicados?\n\n"
            "Arquivos parecidos ou sem marcador claro ficam no lugar para decisao manual.",
        ):
            return
        self._set_busy("Movendo repetidos...")
        thread = threading.Thread(target=self._dedupe_worker, daemon=True)
        thread.start()

    def _dedupe_worker(self) -> None:
        assert self.scan_result is not None
        result = move_duplicates_to_quarantine(
            self.scan_result.root,
            self.scan_result.duplicates,
            dry_run=False,
        )
        self.work_queue.put(("dedupe_done", result))

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
            thread = threading.Thread(target=self._project_apply_worker, args=("selected_duplicate", operation), daemon=True)
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
        thread = threading.Thread(target=self._move_selected_worker, args=(file_path, kind), daemon=True)
        thread.start()

    def _move_selected_worker(self, file_path: str, kind: str) -> None:
        assert self.scan_result is not None
        bucket = "decisao_manual" if kind == "possible" else "duplicado_exato"
        result = move_files_to_quarantine(self.scan_result.root, [file_path], bucket=bucket, dry_run=False)
        self.work_queue.put(("selected_duplicate_done", result))

    def _project_apply_worker(self, action: str, operation: DuplicateOperation | None) -> None:
        assert self.project_report is not None
        if action == "selected_duplicate" and operation is not None:
            report = ProjectReport(
                root=self.project_report.root,
                generated_at=self.project_report.generated_at,
                duplicates=[operation],
            )
            result = apply_project_report(report, organize=False, duplicates=True, import_external=False, yes=True)
        else:
            result = apply_project_report(
                self.project_report,
                organize=action == "organize",
                duplicates=action == "duplicates",
                import_external=False,
                yes=True,
            )
        self.work_queue.put(("project_apply_done", result))

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
                elif event == "project_scan_done":
                    self._on_project_scan_done(payload)  # type: ignore[arg-type]
                elif event in {"apply_done", "dedupe_done", "selected_duplicate_done"}:
                    self._on_apply_done(payload, event)  # type: ignore[arg-type]
                elif event == "project_apply_done":
                    self._on_project_apply_done(payload)  # type: ignore[arg-type]
                elif event == "error":
                    self._on_error(payload)  # type: ignore[arg-type]
        except queue.Empty:
            pass
        self.after(120, self._poll_queue)

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
                        group.sha256[:12] if group.sha256 else "-",
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
        self._append_log(f"Previa concluida: {result.root}")
        for skipped in result.skipped:
            self._append_log(f"Aviso: {skipped}")
        for error in result.errors:
            self._append_log(f"Erro: {error}")
        self._write_document_scan_log(result)
        self._finish_busy()

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
                    "copy",
                    "HD externo",
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
        self._append_log(f"Previa de projetos concluida: {report.root}")
        for warning in report.warnings:
            self._append_log(f"Aviso: {warning}")
        for error in report.errors:
            self._append_log(f"Erro: {error}")
        self._write_project_scan_log(report)
        self._finish_busy()

    def _on_apply_done(self, result: ApplyResult, event: str) -> None:
        labels = {
            "apply_done": "Organizacao",
            "dedupe_done": "Repetidos exatos",
            "selected_duplicate_done": "Item selecionado",
        }
        label = labels.get(event, "Acao")
        self.status_var.set(f"{label}: {len(result.moved)} movimentos, {len(result.errors)} erros")
        self._append_log(f"{label}: {len(result.moved)} movimentos")
        for source, destination in result.moved[:80]:
            self._append_log(f"{source} -> {destination}")
        for skipped in result.skipped:
            self._append_log(f"Ignorado: {skipped}")
        for error in result.errors:
            self._append_log(f"Erro: {error}")
        self._write_document_apply_log(result, label)
        self._finish_busy()

    def _on_project_apply_done(self, result: dict[str, list[str]]) -> None:
        moved = result.get("moved", [])
        copied = result.get("copied", [])
        errors = result.get("errors", [])
        skipped = result.get("skipped", [])
        self.status_var.set(f"Projetos: {len(moved)} movimentos, {len(copied)} copias, {len(errors)} erros")
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
            logger.info("interface=gui modo=Projetos/CAD raiz=%s gerado_em=%s", report.root, report.generated_at)
            for key, value in report.stats.items():
                logger.info("stat.%s=%s", key, value)
            for index, item in enumerate(report.organization, start=1):
                logger.info(
                    "organizacao[%04d] action=%s source=%s destination=%s reason=%s",
                    index,
                    item.action,
                    item.source,
                    item.destination,
                    item.reason,
                )
            for index, item in enumerate(report.duplicates, start=1):
                logger.info(
                    "duplicata[%04d] size=%s sha256=%s source=%s keeper=%s destination=%s reason=%s",
                    index,
                    item.size,
                    item.sha256,
                    item.source,
                    item.keeper,
                    item.destination,
                    item.reason,
                )
            for index, item in enumerate(report.external_candidates, start=1):
                logger.info(
                    "externo[%04d] score=%s drive=%s source=%s destination=%s reasons=%s size=%s",
                    index,
                    item.score,
                    item.drive,
                    item.source,
                    item.destination,
                    "; ".join(item.reasons),
                    item.size,
                )
            for item in report.warnings:
                logger.warning("%s", item)
            for item in report.errors:
                logger.error("%s", item)
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

    def _write_project_apply_log(self, result: dict[str, list[str]]) -> None:
        if not self.active_root:
            return
        logger, log_path = create_operation_logger(self.active_root, mode=MODE_PROJECTS, operation="gui-project-apply")
        try:
            logger.info(
                "interface=gui acao=Projetos movimentos=%s copias=%s ignorados=%s erros=%s",
                len(result.get("moved", [])),
                len(result.get("copied", [])),
                len(result.get("skipped", [])),
                len(result.get("errors", [])),
            )
            for item in result.get("moved", []):
                logger.info("move %s", item)
            for item in result.get("copied", []):
                logger.info("copy %s", item)
            for item in result.get("skipped", []):
                logger.warning("%s", item)
            for item in result.get("errors", []):
                logger.error("%s", item)
        finally:
            close_logger(logger)
        self._append_log(f"Log completo: {log_path}")

    def _on_error(self, exc: object) -> None:
        self.status_var.set("Erro")
        messagebox.showerror("Arruma Dir", str(exc))
        self._append_log(f"Erro: {exc}")
        self._finish_busy()

    def _clear_tree(self, tree: ttk.Treeview) -> None:
        for item in tree.get_children():
            tree.delete(item)

    def _set_busy(self, message: str) -> None:
        self.busy = True
        self.status_var.set(message)
        self._append_log(message)
        self._set_action_buttons()

    def _finish_busy(self) -> None:
        self.busy = False
        self._set_action_buttons()

    def _append_log(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")


def run() -> None:
    app = ArrumaDirApp()
    app.mainloop()
