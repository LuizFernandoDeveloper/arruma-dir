from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

from arruma_dir.gui_charts import build_directory_bars, build_pie_slices, build_ranked_bars, label_margin, percent_text


class GuiChartTests(unittest.TestCase):
    def test_gui_charts_import_does_not_load_matplotlib(self) -> None:
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

        self.assertEqual(result.stdout.strip(), "False")

    def test_build_pie_slices_groups_small_or_excessive_types(self) -> None:
        cases = [
            ({}, []),
            ({".pdf": 10, ".tmp": 0}, [(".pdf (10)", 10)]),
            (
                {".pdf": 60, ".docx": 20, ".jpg": 10, ".tmp": 1, ".bak": 1},
                [(".pdf (60)", 60), (".docx (20)", 20), ("Outros (3 tipos)", 12)],
            ),
        ]
        for summary_data, expected in cases:
            with self.subTest(summary_data=summary_data):
                slices = build_pie_slices(summary_data, min_fraction=0.05, max_named_slices=2)

                self.assertEqual([(item.label, item.count) for item in slices], expected)

    def test_build_ranked_bars_keeps_labels_clean_for_horizontal_chart(self) -> None:
        bars = build_ranked_bars(
            {
                ".pdf": 128,
                ".pdf livro": 40,
                ".pdf padrão empresa": 12,
                ".tmp": 1,
                ".bak": 1,
            },
            min_fraction=0.05,
            max_named_bars=3,
        )

        self.assertEqual(
            [(item.label, item.count) for item in bars],
            [
                (".pdf", 128),
                (".pdf livro", 40),
                (".pdf padrão empresa", 12),
                ("Outros (2 tipos)", 2),
            ],
        )

    def test_percent_text_handles_empty_and_normal_totals(self) -> None:
        self.assertEqual(percent_text(0, 0), "0%")
        self.assertEqual(percent_text(25, 100), "25.0%")

    def test_label_margin_expands_for_long_chart_labels(self) -> None:
        short = label_margin([".pdf", ".jpg"], minimum=0.18, maximum=0.44)
        long = label_margin(["projetos/engenharia/SolidWorks-Electrical"], minimum=0.18, maximum=0.44)

        self.assertEqual(short, 0.18)
        self.assertGreater(long, short)
        self.assertLessEqual(long, 0.44)

    def test_build_directory_bars_keeps_chart_draw_order_and_groups_tail(self) -> None:
        bars = build_directory_bars(
            {
                "projetos": 30,
                "areas": 20,
                "recursos": 10,
                "arquivo": 5,
            },
            max_named_bars=2,
        )

        self.assertEqual(
            [(item.label, item.count) for item in bars],
            [
                ("Outros", 15),
                ("areas", 20),
                ("projetos", 30),
            ],
        )


if __name__ == "__main__":
    unittest.main()
