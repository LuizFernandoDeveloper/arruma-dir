from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arruma_dir.project_organizer import (
    build_organization_plan,
    create_opcao_template,
    scan_projects,
)


class ProjectOrganizerTests(unittest.TestCase):
    def test_opcao_staging_children_are_classified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            staging = root / "organizar" / "4- Projeto Mecanico"
            staging.mkdir(parents=True)
            (staging / "Catalogo Opcao").mkdir()
            (staging / "00000 - Componentes").mkdir()
            (staging / "OP-0041-001-XXX REV00 - Suporte Pinca Opcao M20").mkdir()
            (staging / "047-007-000-REV00 - MONTAGEM DO FORNO").mkdir()

            plan = build_organization_plan(root)
            destinations = {Path(item.source).name: Path(item.destination) for item in plan}

            self.assertIn("Catalogo Opcao", destinations)
            self.assertEqual(destinations["Catalogo Opcao"].parts[-3:-1], ("Opcao", "Catalogos"))
            self.assertEqual(destinations["00000 - Componentes"].parts[-3:-1], ("Opcao", "Biblioteca_Componentes"))
            self.assertEqual(
                destinations["OP-0041-001-XXX REV00 - Suporte Pinca Opcao M20"].parts[-4:-1],
                ("Opcao", "Biblioteca_Componentes", "Itens_OP"),
            )
            self.assertEqual(
                destinations["047-007-000-REV00 - MONTAGEM DO FORNO"].parts[-3:-1],
                ("Opcao", "Projetos_Mecanicos"),
            )

    def test_opcao_template_is_dry_run_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            created = create_opcao_template(root, "047-007-000-REV00 - MONTAGEM DO FORNO", yes=False)

            self.assertTrue(any("01 - Montagem" in path for path in created))
            self.assertFalse((root / "projetos").exists())

    def test_scan_without_hash_reports_opcao_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            staging = root / "organizar" / "4- Projeto Mecanico"
            staging.mkdir(parents=True)
            (staging / "CABOS").mkdir()

            report = scan_projects(root, no_hash=True)

            self.assertEqual(report.stats["organization_moves"], 1)
            self.assertIn("Opcao", report.organization[0].destination)

    def test_scan_reports_file_and_directory_composition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mechanical = root / "organizar" / "4- Projeto Mecanico"
            electrical = root / "organizar" / "1- Projeto Eletrico (Eplan)"
            mechanical.mkdir(parents=True)
            electrical.mkdir(parents=True)
            (mechanical / "peca.step").write_bytes(b"step")
            (mechanical / "desenho.slddrw").write_bytes(b"draw")
            (electrical / "painel.pdf").write_bytes(b"pdf")

            report = scan_projects(root, no_hash=True)

            self.assertEqual(report.file_summary[".step"], 1)
            self.assertEqual(report.file_summary[".slddrw"], 1)
            self.assertEqual(report.file_summary[".pdf"], 1)
            self.assertEqual(report.directory_summary["organizar"], 3)

    def test_loose_cad_file_is_not_organized_out_of_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            staging = root / "organizar" / "4- Projeto Mecanico"
            staging.mkdir(parents=True)
            cad_file = staging / "047-007-000-REV00 - BASE.SLDPRT"
            cad_file.write_bytes(b"solidworks part")

            plan = build_organization_plan(root)

            self.assertNotIn(str(cad_file), {item.source for item in plan})

    def test_project_file_package_is_skipped_by_duplicate_quarantine(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "organizar" / "solid-eletrical" / "estudoDeCaso"
            assets = package / "estudoDeCaso_arquivos"
            assets.mkdir(parents=True)
            (package / ".project").write_text("<projectDescription />", encoding="utf-8")
            (assets / "logo.jpg").write_bytes(b"same asset")
            (assets / "logo copia.jpg").write_bytes(b"same asset")

            report = scan_projects(root)

            self.assertEqual(report.stats["duplicate_moves"], 0)
            self.assertTrue(any("arquivos CAD ignorados" in warning for warning in report.warnings))

    def test_project_file_package_can_be_included_explicitly_in_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "organizar" / "solid-eletrical" / "estudoDeCaso"
            assets = package / "estudoDeCaso_arquivos"
            assets.mkdir(parents=True)
            (package / ".project").write_text("<projectDescription />", encoding="utf-8")
            (assets / "logo.jpg").write_bytes(b"same asset")
            (assets / "logo copia.jpg").write_bytes(b"same asset")

            report = scan_projects(root, include_cad_duplicates=True)

            self.assertEqual(report.stats["duplicate_moves"], 1)


if __name__ == "__main__":
    unittest.main()
