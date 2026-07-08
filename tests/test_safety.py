from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arruma_dir.safety import check_organization_root


class SafetyTests(unittest.TestCase):
    def test_missing_folder_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nao-existe"

            check = check_organization_root(missing, mode="documents")

            self.assertFalse(check.ok)
            self.assertTrue(any("nao existe" in error for error in check.errors))

    def test_projects_mode_warns_when_folder_is_not_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "qualquer"
            root.mkdir()

            check = check_organization_root(root, mode="projects")

            self.assertTrue(check.ok)
            self.assertTrue(any("Projetos/CAD" in warning for warning in check.warnings))

    def test_documents_mode_warns_when_folder_is_not_documents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "downloads"
            root.mkdir()

            check = check_organization_root(root, mode="documents")

            self.assertTrue(check.ok)
            self.assertTrue(any("Documentos/PARA" in warning for warning in check.warnings))


if __name__ == "__main__":
    unittest.main()
