from __future__ import annotations

import ast
import runpy
import unittest
from pathlib import Path
from unittest.mock import patch


class EntryPointTests(unittest.TestCase):
    def test_app_py_can_be_run_directly(self) -> None:
        app_path = str(Path("src") / "arruma_dir" / "app.py")

        with patch("arruma_dir.gui.run") as gui_run:
            runpy.run_path(app_path, run_name="__main__")

        gui_run.assert_called_once_with()

    def test_cli_help_can_be_invoked(self) -> None:
        from arruma_dir.cli import main as cli_main

        with self.assertRaises(SystemExit) as context:
            cli_main(["--help"])

        self.assertEqual(context.exception.code, 0)

    def test_project_cli_help_can_be_invoked(self) -> None:
        from arruma_dir.project_cli import main as project_cli_main

        with self.assertRaises(SystemExit) as context:
            project_cli_main(["--help"])

        self.assertEqual(context.exception.code, 0)

    def test_all_package_modules_parse(self) -> None:
        package_root = Path("src") / "arruma_dir"

        for py_file in package_root.rglob("*.py"):
            with self.subTest(file=str(py_file)):
                ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))

    def test_package_imports_are_absolute(self) -> None:
        package_root = Path("src") / "arruma_dir"
        errors: list[str] = []

        for py_file in package_root.rglob("*.py"):
            if py_file.name == "__init__.py":
                continue

            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level > 0:
                    errors.append(f"{py_file}:{node.lineno} usa import relativo")

        self.assertEqual(errors, [])

    def test_project_organizer_is_importable_for_packaged_gui(self) -> None:
        import arruma_dir.project_organizer as project_organizer

        self.assertTrue(hasattr(project_organizer, "scan_projects"))

    def test_gui_exposes_rollback_handler(self) -> None:
        from arruma_dir.gui import ArrumaDirApp

        self.assertTrue(callable(getattr(ArrumaDirApp, "rollback_last_action", None)))

    def test_legacy_project_script_points_to_project_cli(self) -> None:
        script_path = Path("scripts") / "organiza_projetos.py"
        tree = ast.parse(script_path.read_text(encoding="utf-8"), filename=str(script_path))
        imports = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]

        self.assertTrue(
            any(node.module == "arruma_dir.project_cli" and any(alias.name == "main" for alias in node.names) for node in imports)
        )

    def test_pyinstaller_spec_keeps_project_modules_visible(self) -> None:
        spec = Path("ArrumaDir.spec").read_text(encoding="utf-8")

        self.assertIn("'arruma_dir.project_organizer'", spec)
        self.assertIn("'arruma_dir.project_cli'", spec)


if __name__ == "__main__":
    unittest.main()
