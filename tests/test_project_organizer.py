from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arruma_dir.project_organizer import (
    DuplicateOperation,
    MoveOperation,
    ProjectReport,
    apply_report,
    build_organization_plan,
    create_opcao_template,
    duplicate_quarantine_target,
    execute_copy,
    execute_merge_dir,
    execute_move,
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

    def test_apply_report_records_structured_move_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            staging = root / "organizar" / "4- Projeto Mecanico"
            staging.mkdir(parents=True)
            (staging / "CABOS").mkdir()

            report = scan_projects(root, no_hash=True)
            result = apply_report(report, organize=True, duplicates=False, import_external=False, yes=True)

            self.assertEqual(len(result["moved"]), 1)
            self.assertEqual(len(result["moved_pairs"]), 1)
            source, destination = result["moved_pairs"][0]
            self.assertFalse(Path(source).exists())
            self.assertTrue(Path(destination).exists())

    def test_project_merge_dir_recursively_merges_existing_canonical_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_root = root / "Ramtech"
            source_dwg = source_root / "Projetos" / "P20051-0001 - CLIENTE" / "3- Projeto Eletrico (DWG)"
            target_dwg = root / "projetos" / "Ramtech" / "Projetos" / "P20051-0001 - CLIENTE" / "3- Projeto Eletrico (DWG)"
            source_dwg.mkdir(parents=True)
            target_dwg.mkdir(parents=True)
            (source_dwg / "P20051-PAINEL-NOVO.dwg").write_bytes(b"novo")
            (target_dwg / "P20051-EXISTENTE.dwg").write_bytes(b"existente")

            report = scan_projects(root, no_hash=True)
            merge_items = [item for item in report.organization if item.action == "merge_dir"]

            self.assertEqual(len(merge_items), 1)
            result = apply_report(report, organize=True, duplicates=False, import_external=False, yes=True)

            self.assertEqual(result["errors"], [])
            self.assertFalse(source_root.exists())
            self.assertTrue((target_dwg / "P20051-PAINEL-NOVO.dwg").exists())
            self.assertTrue((target_dwg / "P20051-EXISTENTE.dwg").exists())
            self.assertFalse((root / "projetos" / "Ramtech" / "Projetos (2)").exists())

    def test_project_merge_dir_dry_run_reports_nested_targets_without_touching_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "Ramtech"
            destination = root / "projetos" / "Ramtech"
            source_nested = source / "Projetos" / "P20051-0001 - CLIENTE"
            destination_nested = destination / "Projetos" / "P20051-0001 - CLIENTE"
            source_nested.mkdir(parents=True)
            destination_nested.mkdir(parents=True)
            source_file = source_nested / "novo.pdf"
            source_file.write_bytes(b"novo")
            (destination_nested / "existente.pdf").write_bytes(b"existente")

            moved = execute_merge_dir(source, destination, dry_run=True)

            self.assertEqual(moved, [(str(source_file), str(destination_nested / "novo.pdf"))])
            self.assertTrue(source_file.exists())
            self.assertFalse((destination_nested / "novo.pdf").exists())

    def test_project_merge_dir_refuses_destination_inside_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "Ramtech"
            destination = source / "projetos" / "Ramtech"
            source.mkdir()

            with self.assertRaises(ValueError):
                execute_merge_dir(source, destination, dry_run=True)

    def test_project_apply_rejects_organization_source_outside_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside_tmp:
            root = Path(tmp)
            outside = Path(outside_tmp) / "fora.txt"
            outside.write_text("nao mover", encoding="utf-8")
            report = ProjectReport(
                root=str(root),
                generated_at="agora",
                organization=[
                    MoveOperation("move", str(outside), str(root / "projetos" / "fora.txt"), "relatorio adulterado")
                ],
            )

            result = apply_report(report, organize=True, duplicates=False, import_external=False, yes=True)

            self.assertEqual(result["moved"], [])
            self.assertTrue(result["errors"])
            self.assertTrue(outside.exists())
            self.assertFalse((root / "projetos" / "fora.txt").exists())

    def test_project_apply_rejects_duplicate_source_outside_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside_tmp:
            root = Path(tmp)
            outside = Path(outside_tmp) / "duplicado.pdf"
            outside.write_bytes(b"same")
            report = ProjectReport(
                root=str(root),
                generated_at="agora",
                duplicates=[
                    DuplicateOperation(
                        source=str(outside),
                        destination=str(root / "_arruma_projetos" / "duplicados" / "duplicado.pdf"),
                        keeper=str(root / "original.pdf"),
                        sha256="a" * 64,
                        size=4,
                        reason="relatorio adulterado",
                    )
                ],
            )

            result = apply_report(report, organize=False, duplicates=True, import_external=False, yes=True)

            self.assertEqual(result["moved"], [])
            self.assertTrue(result["errors"])
            self.assertTrue(outside.exists())

    def test_project_move_and_copy_dry_run_report_unique_destination(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            move_source = root / "novo.pdf"
            copy_source = root / "manual.pdf"
            existing_move = root / "destino.pdf"
            existing_copy = root / "copia.pdf"
            move_source.write_bytes(b"move")
            copy_source.write_bytes(b"copy")
            existing_move.write_bytes(b"existe")
            existing_copy.write_bytes(b"existe")

            moved = execute_move(move_source, existing_move, dry_run=True)
            copied = execute_copy(copy_source, existing_copy, dry_run=True)

            self.assertEqual(Path(moved[1]).name, "destino (2).pdf")
            self.assertEqual(Path(copied[1]).name, "copia (2).pdf")
            self.assertTrue(move_source.exists())
            self.assertEqual(existing_move.read_bytes(), b"existe")

    def test_project_duplicate_quarantine_target_preserves_file_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "organizar" / "P20051-PAINEL FINAL (1).dwg"
            source.parent.mkdir()
            source.write_bytes(b"dwg")

            target = duplicate_quarantine_target(root, source, "a" * 64)

            self.assertEqual(target.suffix, ".dwg")
            self.assertEqual(target.name, "p20051_painel_final_1.dwg")

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

    def test_project_scan_separates_company_standard_and_book_pdfs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            books = root / "projetos" / "Referencias" / "Biblioteca"
            standards = root / "projetos" / "Ramtech" / "PADRAO RAMTECH"
            normal_dir = root / "organizar"
            books.mkdir(parents=True)
            standards.mkdir(parents=True)
            normal_dir.mkdir()
            (books / "Implementing Domain-Driven Design.pdf").write_bytes(b"book")
            (standards / "IT 05.01 - Criacao pasta virtual e montagem pasta fisica R01.pdf").write_bytes(b"standard")
            (normal_dir / "painel.pdf").write_bytes(b"normal")

            report = scan_projects(root, no_hash=True)

            self.assertEqual(report.file_summary[".pdf livro"], 1)
            self.assertEqual(report.file_summary[".pdf padrão empresa"], 1)
            self.assertEqual(report.file_summary[".pdf"], 1)

    def test_loose_cad_file_is_not_organized_out_of_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            staging = root / "organizar" / "4- Projeto Mecanico"
            staging.mkdir(parents=True)
            cad_file = staging / "047-007-000-REV00 - BASE.SLDPRT"
            cad_file.write_bytes(b"solidworks part")

            plan = build_organization_plan(root)

            self.assertNotIn(str(cad_file), {item.source for item in plan})

    def test_dwg_with_project_code_goes_to_matching_project_dwg_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            existing_project = root / "projetos" / "Ramtech" / "Projetos" / "P20051-792589 - BEM BRASIL"
            existing_project.mkdir(parents=True)
            staging = root / "organizar"
            staging.mkdir()
            drawing = staging / "P20051-PAINEL-GERAL.dwg"
            drawing.write_bytes(b"dwg")

            plan = build_organization_plan(root)
            by_source = {item.source: item for item in plan}

            self.assertIn(str(drawing), by_source)
            destination = Path(by_source[str(drawing)].destination)
            self.assertEqual(destination.parent.name, "3- Projeto Eletrico (DWG)")
            self.assertEqual(destination.parent.parent, existing_project)
            self.assertIn("extensao .dwg", by_source[str(drawing)].reason)

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

    def test_solidworks_electrical_ewg_is_skipped_by_duplicate_quarantine(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "organizar" / "solid-eletrical" / "estudoDeCaso"
            package.mkdir(parents=True)
            (package / "folha01.ewg").write_bytes(b"same drawing")
            (package / "folha01 copia.ewg").write_bytes(b"same drawing")

            report = scan_projects(root)

            self.assertEqual(report.stats["duplicate_moves"], 0)
            self.assertTrue(any("arquivos CAD ignorados" in warning for warning in report.warnings))

    def test_solidworks_electrical_ewg_can_be_included_explicitly_in_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "organizar" / "solid-eletrical" / "estudoDeCaso"
            package.mkdir(parents=True)
            (package / "folha01.ewg").write_bytes(b"same drawing")
            (package / "folha01 copia.ewg").write_bytes(b"same drawing")

            report = scan_projects(root, include_cad_duplicates=True)

            self.assertEqual(report.stats["duplicate_moves"], 1)

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

    def test_populate_base_external_scan_skips_content_already_in_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as external_tmp:
            root = Path(tmp)
            base = root / "projetos" / "Ramtech" / "Projetos"
            base.mkdir(parents=True)
            (base / "P20051-EXISTENTE.pdf").write_bytes(b"ja existe")

            drive = Path(external_tmp)
            external_project = drive / "Ramtech" / "P20051 - Cliente"
            external_project.mkdir(parents=True)
            existing_copy = external_project / "P20051-EXISTENTE copia.pdf"
            existing_copy.write_bytes(b"ja existe")
            missing = external_project / "P20051-NOVO.pdf"
            missing.write_bytes(b"conteudo novo")

            report = scan_projects(
                root,
                external=True,
                external_drives=[drive],
                populate_base=True,
                no_hash=True,
                min_external_score=6,
            )

            self.assertEqual([Path(item.source).name for item in report.external_candidates], [missing.name])
            candidate = report.external_candidates[0]
            self.assertEqual(candidate.decision, "popular_base")
            self.assertIn("conteudo ausente na base atual", candidate.reasons)
            self.assertIn("projetos", Path(candidate.destination).parts)
            self.assertNotIn("_arruma_projetos", Path(candidate.destination).parts)
            self.assertTrue(any("ja existem na base" in warning for warning in report.warnings))

    def test_populate_base_apply_copies_missing_external_candidate_to_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as external_tmp:
            root = Path(tmp)
            (root / "projetos").mkdir()
            drive = Path(external_tmp)
            source = drive / "Opcao" / "OP-0041-001-XXX REV00 - Suporte.pdf"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"novo opcao")

            report = scan_projects(
                root,
                external=True,
                external_drives=[drive],
                populate_base=True,
                no_hash=True,
                min_external_score=6,
            )
            result = apply_report(report, organize=False, duplicates=False, import_external=True, yes=True)

            self.assertEqual(len(result["copied_pairs"]), 1)
            _, destination = result["copied_pairs"][0]
            self.assertTrue(Path(destination).exists())
            self.assertEqual(Path(destination).read_bytes(), b"novo opcao")
            self.assertIn("projetos", Path(destination).parts)


if __name__ == "__main__":
    unittest.main()
