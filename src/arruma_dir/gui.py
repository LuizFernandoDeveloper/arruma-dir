from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

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


class ArrumaDirApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Arruma Dir")
        self.minsize(980, 620)
        self.scan_result: ScanResult | None = None
        self.duplicate_rows: dict[str, dict[str, object]] = {}
        self.work_queue: queue.Queue[tuple[str, object]] = queue.Queue()

        self.path_var = tk.StringVar(value=str(default_documents_path()))
        self.compat_var = tk.BooleanVar(value=False)
        self.duplicates_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Pronto")

        self._build_layout()
        self.after(120, self._poll_queue)

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        top = ttk.Frame(self, padding=(12, 12, 12, 8))
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="Diretorio").grid(row=0, column=0, sticky="w", padx=(0, 8))
        path_entry = ttk.Entry(top, textvariable=self.path_var)
        path_entry.grid(row=0, column=1, sticky="ew")
        ttk.Button(top, text="Escolher", command=self.choose_directory).grid(row=0, column=2, padx=(8, 0))

        options = ttk.Frame(self, padding=(12, 0, 12, 8))
        options.grid(row=1, column=0, sticky="ew")
        ttk.Checkbutton(options, text="Nomes compativeis", variable=self.compat_var).pack(side="left")
        ttk.Checkbutton(options, text="Buscar repetidos", variable=self.duplicates_var).pack(side="left", padx=(18, 0))
        ttk.Button(options, text="Escanear", command=self.scan).pack(side="right")
        ttk.Button(options, text="Exportar JSON", command=self.export_json).pack(side="right", padx=(0, 8))
        ttk.Button(options, text="Mover selecionado", command=self.move_selected_duplicate).pack(side="right", padx=(0, 8))
        ttk.Button(options, text="Mover copias exatas", command=self.move_duplicates).pack(side="right", padx=(0, 8))
        ttk.Button(options, text="Aplicar organizacao", command=self.apply_organization).pack(side="right", padx=(0, 8))

        notebook = ttk.Notebook(self)
        notebook.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 8))

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
        status.grid(row=3, column=0, sticky="ew")
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
            tree.column(column, width=140 if column in {"action", "category", "size", "hash"} else 320)
        return tree

    def choose_directory(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.path_var.get() or str(Path.home()))
        if selected:
            self.path_var.set(selected)

    def scan(self) -> None:
        path = self.path_var.get().strip()
        if not path:
            messagebox.showwarning("Arruma Dir", "Escolha um diretorio.")
            return
        self._set_busy("Escaneando...")
        self._clear_tree(self.plan_tree)
        self._clear_tree(self.duplicate_tree)
        thread = threading.Thread(
            target=self._scan_worker,
            args=(path, self.compat_var.get(), self.duplicates_var.get()),
            daemon=True,
        )
        thread.start()

    def _scan_worker(self, path: str, compat_names: bool, include_duplicates: bool) -> None:
        try:
            result = scan_directory(path, compat_names=compat_names, include_duplicates=include_duplicates)
            self.work_queue.put(("scan_done", result))
        except Exception as exc:  # noqa: BLE001 - shown in GUI.
            self.work_queue.put(("error", exc))

    def apply_organization(self) -> None:
        if not self.scan_result or not self.scan_result.plan:
            messagebox.showinfo("Arruma Dir", "Nenhum plano carregado.")
            return
        answer = messagebox.askyesno(
            "Aplicar organizacao",
            "Mover os itens do plano agora? Nada sera apagado.",
        )
        if not answer:
            return
        self._set_busy("Aplicando organizacao...")
        thread = threading.Thread(target=self._apply_worker, daemon=True)
        thread.start()

    def _apply_worker(self) -> None:
        assert self.scan_result is not None
        result = apply_plan(self.scan_result.plan, self.scan_result.root, dry_run=False)
        self.work_queue.put(("apply_done", result))

    def move_duplicates(self) -> None:
        if not self.scan_result or not self.scan_result.duplicates:
            messagebox.showinfo("Arruma Dir", "Nenhum repetido carregado.")
            return
        answer = messagebox.askyesno(
            "Mover copias exatas",
            "Mover somente copias exatamente iguais com marcador de copia para _duplicados? Os demais ficam para decisao.",
        )
        if not answer:
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
        selected = self.duplicate_tree.selection()
        if not selected:
            messagebox.showinfo("Arruma Dir", "Selecione um item na aba Repetidos.")
            return
        row = self.duplicate_rows.get(selected[0])
        if not row or not self.scan_result:
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
            answer = messagebox.askyesno(
                "Possivel duplicado",
                f"Este arquivo tem diferencas e sera mantido por padrao.\n\n{differences}\n\nMover mesmo assim?",
            )
        else:
            answer = messagebox.askyesno("Mover selecionado", "Mover este arquivo para _duplicados?")
        if not answer:
            return

        self._set_busy("Movendo item selecionado...")
        thread = threading.Thread(target=self._move_selected_worker, args=(file_path, kind), daemon=True)
        thread.start()

    def _move_selected_worker(self, file_path: str, kind: str) -> None:
        assert self.scan_result is not None
        bucket = "decisao_manual" if kind == "possible" else "duplicado_exato"
        result = move_files_to_quarantine(self.scan_result.root, [file_path], bucket=bucket, dry_run=False)
        self.work_queue.put(("selected_duplicate_done", result))

    def export_json(self) -> None:
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
                elif event in {"apply_done", "dedupe_done", "selected_duplicate_done"}:
                    self._on_apply_done(payload, event)  # type: ignore[arg-type]
                elif event == "error":
                    self._on_error(payload)  # type: ignore[arg-type]
        except queue.Empty:
            pass
        self.after(120, self._poll_queue)

    def _on_scan_done(self, result: ScanResult) -> None:
        self.scan_result = result
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
        self._append_log(f"Scan concluido: {result.root}")
        for skipped in result.skipped:
            self._append_log(f"Aviso: {skipped}")
        for error in result.errors:
            self._append_log(f"Erro: {error}")

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

    def _on_error(self, exc: object) -> None:
        self.status_var.set("Erro")
        messagebox.showerror("Arruma Dir", str(exc))
        self._append_log(f"Erro: {exc}")

    def _clear_tree(self, tree: ttk.Treeview) -> None:
        for item in tree.get_children():
            tree.delete(item)

    def _set_busy(self, message: str) -> None:
        self.status_var.set(message)
        self._append_log(message)

    def _append_log(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")


def run() -> None:
    app = ArrumaDirApp()
    app.mainloop()
