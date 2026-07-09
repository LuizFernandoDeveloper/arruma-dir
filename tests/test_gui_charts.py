from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from arruma_dir.gui_charts import build_directory_bars, build_pie_slices


def test_gui_charts_import_does_not_load_matplotlib() -> None:
    env = os.environ.copy()
    src_path = str(Path(__file__).resolve().parents[1] / "src")
    env["PYTHONPATH"] = src_path + os.pathsep + env.get("PYTHONPATH", "")

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import arruma_dir.gui_charts; print('matplotlib' in sys.modules)",
        ],
        check=True,
        capture_output=True,
        env=env,
        text=True,
    )

    assert result.stdout.strip() == "False"


@pytest.mark.parametrize(
    ("summary_data", "expected"),
    [
        ({}, []),
        ({".pdf": 10, ".tmp": 0}, [(".pdf (10)", 10)]),
        (
            {".pdf": 60, ".docx": 20, ".jpg": 10, ".tmp": 1, ".bak": 1},
            [(".pdf (60)", 60), (".docx (20)", 20), ("Outros (3 tipos)", 12)],
        ),
    ],
)
def test_build_pie_slices_groups_small_or_excessive_types(
    summary_data: dict[str, int],
    expected: list[tuple[str, int]],
) -> None:
    slices = build_pie_slices(summary_data, min_fraction=0.05, max_named_slices=2)

    assert [(item.label, item.count) for item in slices] == expected


def test_build_directory_bars_keeps_chart_draw_order_and_groups_tail() -> None:
    bars = build_directory_bars(
        {
            "projetos": 30,
            "areas": 20,
            "recursos": 10,
            "arquivo": 5,
        },
        max_named_bars=2,
    )

    assert [(item.label, item.count) for item in bars] == [
        ("Outros", 15),
        ("areas", 20),
        ("projetos", 30),
    ]
