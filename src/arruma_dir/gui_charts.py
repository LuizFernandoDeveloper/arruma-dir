from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure


@dataclass(frozen=True)
class ChartPalette:
    app_bg: str
    muted_fg: str
    title_fg: str
    axis_fg: str
    grid_fg: str
    bar_colors: tuple[str, ...]


@dataclass(frozen=True)
class ChartSlice:
    label: str
    count: int


DEFAULT_PALETTE = ChartPalette(
    app_bg="#f5f7fb",
    muted_fg="#64748b",
    title_fg="#0f172a",
    axis_fg="#334155",
    grid_fg="#e2e8f0",
    bar_colors=("#2563eb", "#0f766e", "#f59e0b", "#dc2626", "#7c3aed", "#475569"),
)


def build_ranked_bars(
    summary_data: dict[str, int],
    *,
    min_fraction: float = 0.03,
    max_named_bars: int = 10,
    other_label: str = "Outros",
) -> list[ChartSlice]:
    total_items = sum(summary_data.values())
    if total_items <= 0:
        return []

    bars: list[ChartSlice] = []
    other_size = 0
    other_count = 0

    for label, count in sorted(summary_data.items(), key=lambda item: item[1], reverse=True):
        if count <= 0:
            continue
        if count / total_items >= min_fraction and len(bars) < max_named_bars:
            bars.append(ChartSlice(label, count))
        else:
            other_size += count
            other_count += 1

    if other_size > 0:
        suffix = f" ({other_count} tipos)" if other_count else ""
        bars.append(ChartSlice(f"{other_label}{suffix}", other_size))

    return bars


def build_pie_slices(
    summary_data: dict[str, int],
    *,
    min_fraction: float = 0.01,
    max_named_slices: int = 15,
) -> list[ChartSlice]:
    return [
        ChartSlice(f"{item.label} ({item.count})" if not item.label.startswith("Outros") else item.label, item.count)
        for item in build_ranked_bars(
            summary_data,
            min_fraction=min_fraction,
            max_named_bars=max_named_slices,
        )
    ]


def build_directory_bars(directory_data: dict[str, int], *, max_named_bars: int = 12) -> list[ChartSlice]:
    positive_items = [(name, count) for name, count in directory_data.items() if count > 0]
    if not positive_items:
        return []

    sorted_data = sorted(positive_items, key=lambda item: item[1], reverse=True)
    top_items = sorted_data[:max_named_bars]
    other_count = sum(count for _, count in sorted_data[max_named_bars:])
    if other_count:
        top_items.append(("Outros", other_count))

    return [ChartSlice(name, count) for name, count in reversed(top_items)]


def percent_text(count: int, total: int) -> str:
    if total <= 0:
        return "0%"
    percent = (count / total) * 100
    return f"{percent:.1f}%"


class LazyChartDeck:
    def __init__(
        self,
        summary_frame: ttk.Frame,
        directory_frame: ttk.Frame,
        *,
        log: Callable[[str], None],
        palette: ChartPalette = DEFAULT_PALETTE,
    ) -> None:
        self.summary_frame = summary_frame
        self.directory_frame = directory_frame
        self.log = log
        self.palette = palette

        self.summary_canvas: FigureCanvasTkAgg | None = None
        self.summary_figure: Figure | None = None
        self.summary_ax: Any | None = None
        self.directory_canvas: FigureCanvasTkAgg | None = None
        self.directory_figure: Figure | None = None
        self.directory_ax: Any | None = None

        self._show_placeholders()

    def _show_placeholders(self) -> None:
        ttk.Label(
            self.summary_frame,
            text="Gere uma previa para ver o grafico.",
            style="Muted.TLabel",
        ).pack(expand=True)
        ttk.Label(
            self.directory_frame,
            text="Gere uma previa para ver os diretorios.",
            style="Muted.TLabel",
        ).pack(expand=True)

    def clear(self) -> None:
        self._clear_file_type_chart()
        self._clear_directory_chart()

    def update_file_summary(self, summary_data: dict[str, int]) -> None:
        bars = build_ranked_bars(summary_data)
        if not bars:
            self._clear_file_type_chart()
            return
        if not self._ensure_canvases():
            return

        total_files = sum(summary_data.values())
        ordered_bars = list(reversed(bars))
        labels = [item.label for item in ordered_bars]
        sizes = [item.count for item in ordered_bars]
        colors = [self.palette.bar_colors[index % len(self.palette.bar_colors)] for index in range(len(labels))]

        self.summary_ax.clear()
        self.summary_ax.barh(labels, sizes, color=colors)
        self.summary_ax.set_title(f"Distribuicao de {total_files} arquivos por tipo", color=self.palette.title_fg)
        self.summary_ax.set_xlabel("Arquivos")
        self.summary_ax.tick_params(axis="x", colors=self.palette.axis_fg)
        self.summary_ax.tick_params(axis="y", colors=self.palette.axis_fg, labelsize=9)
        self.summary_ax.grid(axis="x", color=self.palette.grid_fg, linewidth=0.8)
        self._style_bar_axes(self.summary_ax)
        for index, count in enumerate(sizes):
            self.summary_ax.text(
                count,
                index,
                f" {count} ({percent_text(count, total_files)})",
                va="center",
                color=self.palette.title_fg,
                fontsize=8,
            )
        max_value = max(sizes)
        self.summary_ax.set_xlim(0, max_value * 1.22)
        self.summary_figure.subplots_adjust(left=0.16, right=0.93, top=0.86, bottom=0.18)
        if self.summary_canvas:
            self.summary_canvas.draw()

    def update_directory_summary(self, directory_data: dict[str, int]) -> None:
        bars = build_directory_bars(directory_data)
        if not bars:
            self._clear_directory_chart()
            return
        if not self._ensure_canvases():
            return

        labels = [item.label for item in bars]
        sizes = [item.count for item in bars]
        total_files = sum(directory_data.values())
        colors = [self.palette.bar_colors[index % len(self.palette.bar_colors)] for index in range(len(labels))]

        self.directory_ax.clear()
        self.directory_ax.barh(labels, sizes, color=colors)
        self.directory_ax.set_title(f"Composicao de {total_files} Arquivos por Diretorio", color=self.palette.title_fg)
        self.directory_ax.set_xlabel("Arquivos")
        self.directory_ax.tick_params(axis="x", colors=self.palette.axis_fg)
        self.directory_ax.tick_params(axis="y", colors=self.palette.axis_fg, labelsize=8)
        self.directory_ax.grid(axis="x", color=self.palette.grid_fg, linewidth=0.8)
        self._style_bar_axes(self.directory_ax)
        for index, count in enumerate(sizes):
            self.directory_ax.text(
                count,
                index,
                f" {count} ({percent_text(count, total_files)})",
                va="center",
                color=self.palette.title_fg,
                fontsize=8,
            )
        max_value = max(sizes)
        self.directory_ax.set_xlim(0, max_value * 1.22)
        if self.directory_canvas:
            self.directory_canvas.draw()

    def _ensure_canvases(self) -> bool:
        if self.summary_ax and self.directory_ax:
            return True

        try:
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            from matplotlib.figure import Figure
        except Exception as exc:  # noqa: BLE001 - charts are optional for the GUI flow.
            self.log(f"Graficos indisponiveis: {exc}")
            return False

        for child in self.summary_frame.winfo_children():
            child.destroy()
        self.summary_figure = Figure(figsize=(8, 3.2), dpi=100, facecolor=self.palette.app_bg)
        self.summary_ax = self.summary_figure.add_subplot(111)
        self.summary_ax.set_facecolor(self.palette.app_bg)
        self.summary_figure.subplots_adjust(left=0.16, right=0.93, top=0.86, bottom=0.18)
        self.summary_canvas = FigureCanvasTkAgg(self.summary_figure, self.summary_frame)
        self.summary_canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        for child in self.directory_frame.winfo_children():
            child.destroy()
        self.directory_figure = Figure(figsize=(5, 4), dpi=100, facecolor=self.palette.app_bg)
        self.directory_ax = self.directory_figure.add_subplot(111)
        self.directory_ax.set_facecolor(self.palette.app_bg)
        self.directory_figure.subplots_adjust(left=0.28, right=0.95, top=0.9, bottom=0.12)
        self.directory_canvas = FigureCanvasTkAgg(self.directory_figure, self.directory_frame)
        self.directory_canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        return True

    def _style_bar_axes(self, axis: Any) -> None:
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)
        axis.spines["left"].set_color("#cbd5e1")
        axis.spines["bottom"].set_color("#cbd5e1")

    def _clear_file_type_chart(self) -> None:
        if not self.summary_ax:
            return
        self.summary_ax.clear()
        self.summary_ax.set_title("Distribuicao de Arquivos por Tipo", color=self.palette.muted_fg)
        self.summary_ax.text(
            0.5,
            0.5,
            "Gere uma previa para ver o grafico.",
            ha="center",
            va="center",
            color=self.palette.muted_fg,
            fontsize=10,
        )
        if self.summary_canvas:
            self.summary_canvas.draw()

    def _clear_directory_chart(self) -> None:
        if not self.directory_ax:
            return
        self.directory_ax.clear()
        self.directory_ax.set_title("Composicao por Diretorio", color=self.palette.muted_fg)
        self.directory_ax.text(
            0.5,
            0.5,
            "Gere uma previa para ver os diretorios.",
            ha="center",
            va="center",
            color=self.palette.muted_fg,
            fontsize=10,
            transform=self.directory_ax.transAxes,
        )
        self.directory_ax.set_axis_off()
        if self.directory_canvas:
            self.directory_canvas.draw()
