from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arruma_dir.gui import ArrumaDirApp
from arruma_dir.organizer import DuplicateGroup, ScanResult


class FakeVar:
    def __init__(self) -> None:
        self.value = ""

    def set(self, value: object) -> None:
        self.value = str(value)

    def get(self) -> str:
        return self.value


class FakeTree:
    def __init__(self, item_ids: list[str]) -> None:
        self.rows = {item_id: {"tags": ()} for item_id in item_ids}

    def exists(self, item_id: str) -> bool:
        return item_id in self.rows

    def item(self, item_id: str, **kwargs: object) -> dict[str, object]:
        if "tags" in kwargs:
            self.rows[item_id]["tags"] = tuple(kwargs["tags"])  # type: ignore[arg-type]
        return self.rows[item_id]

    def delete(self, item_id: str) -> None:
        self.rows.pop(item_id, None)


def make_duplicate_app() -> ArrumaDirApp:
    app = object.__new__(ArrumaDirApp)
    app.duplicate_tree = FakeTree(["keeper", "copy1", "copy2", "possible1", "possible2"])
    app.duplicate_rows = {
        "keeper": {"file": "C:/docs/manual.pdf", "kind": "exact", "role": "principal", "group_id": "document:0"},
        "copy1": {"file": "C:/docs/manual (1).pdf", "kind": "exact", "role": "repetido", "group_id": "document:0"},
        "copy2": {"file": "C:/backup/manual.pdf", "kind": "exact", "role": "repetido", "group_id": "document:0"},
        "possible1": {"file": "C:/docs/relatorio.pdf", "kind": "possible", "role": "revisar", "group_id": "document:1"},
        "possible2": {
            "file": "C:/docs/relatorio copia.pdf",
            "kind": "possible",
            "role": "revisar",
            "group_id": "document:1",
        },
    }
    app.summary_vars = {
        "duplicates": FakeVar(),
        "possible": FakeVar(),
    }
    app.scan_result = ScanResult(
        root="C:/docs",
        generated_at="agora",
        duplicates=[
            DuplicateGroup(
                sha256="a" * 64,
                size=4,
                files=["C:/docs/manual.pdf", "C:/docs/manual (1).pdf", "C:/backup/manual.pdf"],
            ),
            DuplicateGroup(
                sha256="",
                size=0,
                files=["C:/docs/relatorio.pdf", "C:/docs/relatorio copia.pdf"],
                kind="possible",
                differences=["tamanhos diferentes"],
            ),
        ],
    )
    app.project_report = None
    app.after = lambda _delay, callback: callback()  # type: ignore[method-assign]
    return app


class GuiBehaviorTests(unittest.TestCase):
    def test_plan_diagram_renders_current_and_future_side_by_side(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = object.__new__(ArrumaDirApp)

            diagram = app._build_plan_diagram(
                str(root),
                [
                    ("merge_dir", str(root / "10-engenharia"), str(root / "recursos" / "engenharia")),
                    ("move", str(root / "plc"), str(root / "projetos" / "automacao_codigo" / "plc")),
                ],
            )

        header = next(line for line in diagram.splitlines() if "Destino atual" in line)
        self.assertIn("Destino futuro", header)
        self.assertIn("10-engenharia [merge_dir]", diagram)
        self.assertIn("recursos", diagram)
        self.assertIn("automacao_codigo", diagram)

    def test_duplicate_pending_marks_exact_rows_without_touching_possible_rows(self) -> None:
        app = make_duplicate_app()

        app._mark_duplicate_rows_pending()

        self.assertEqual(app.duplicate_tree.rows["keeper"]["tags"], ("kept",))
        self.assertEqual(app.duplicate_tree.rows["copy1"]["tags"], ("warning",))
        self.assertEqual(app.duplicate_tree.rows["copy2"]["tags"], ("warning",))
        self.assertEqual(app.duplicate_tree.rows["possible1"]["tags"], ())

    def test_confirmation_code_ignores_case_and_outer_spaces(self) -> None:
        self.assertTrue(ArrumaDirApp._confirmation_matches(" aplicar ", "APLICAR"))
        self.assertTrue(ArrumaDirApp._confirmation_matches("mover", "MOVER"))
        self.assertFalse(ArrumaDirApp._confirmation_matches("aplica", "APLICAR"))

    def test_set_summary_updates_warning_counter(self) -> None:
        app = object.__new__(ArrumaDirApp)
        app.summary_vars = {
            "planned": FakeVar(),
            "duplicates": FakeVar(),
            "possible": FakeVar(),
            "external": FakeVar(),
            "warnings": FakeVar(),
            "errors": FakeVar(),
        }
        app.next_step_var = FakeVar()

        app._set_summary(
            planned=3,
            duplicates=2,
            possible=1,
            external=4,
            errors=0,
            warnings=7,
            next_step="Revise antes de aplicar.",
        )

        self.assertEqual(app.summary_vars["warnings"].get(), "7")
        self.assertEqual(app.next_step_var.get(), "Revise antes de aplicar.")

    def test_partial_duplicate_move_keeps_group_and_updates_scan_result(self) -> None:
        app = make_duplicate_app()

        app._remove_moved_duplicate_rows(["C:/docs/manual (1).pdf"])

        self.assertNotIn("copy1", app.duplicate_tree.rows)
        self.assertIn("keeper", app.duplicate_tree.rows)
        self.assertIn("copy2", app.duplicate_tree.rows)
        self.assertEqual(app.summary_vars["duplicates"].get(), "1")
        self.assertEqual(app.summary_vars["possible"].get(), "1")
        self.assertIsNotNone(app.scan_result)
        self.assertEqual(app.scan_result.duplicates[0].files, ["C:/docs/manual.pdf", "C:/backup/manual.pdf"])

    def test_complete_duplicate_group_move_removes_keeper_row_and_counter(self) -> None:
        app = make_duplicate_app()

        app._remove_moved_duplicate_rows(["C:/docs/manual (1).pdf", "C:/backup/manual.pdf"])

        self.assertNotIn("keeper", app.duplicate_tree.rows)
        self.assertNotIn("copy1", app.duplicate_tree.rows)
        self.assertNotIn("copy2", app.duplicate_tree.rows)
        self.assertIn("possible1", app.duplicate_tree.rows)
        self.assertEqual(app.summary_vars["duplicates"].get(), "0")
        self.assertEqual(app.summary_vars["possible"].get(), "1")
        self.assertIsNotNone(app.scan_result)
        self.assertEqual([group.kind for group in app.scan_result.duplicates], ["possible"])


if __name__ == "__main__":
    unittest.main()
