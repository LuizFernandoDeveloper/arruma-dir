from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arruma_dir.organizer import (
    apply_plan,
    choose_duplicate_keeper,
    classify_entry,
    clean_leaf_name,
    duplicate_hash_label,
    find_duplicate_files,
    move_duplicates_to_quarantine,
    rollback_moves,
    scan_directory,
    strip_leading_number,
)


class OrganizerTests(unittest.TestCase):
    def test_strip_leading_number(self) -> None:
        self.assertEqual(strip_leading_number("7 -  Estudos"), "Estudos")
        self.assertEqual(strip_leading_number("10-engenharia"), "engenharia")
        self.assertEqual(strip_leading_number("sem numero"), "sem numero")

    def test_clean_leaf_name_compat(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "8 - Portifolio Programacao de CNC"
            path.mkdir()
            self.assertEqual(clean_leaf_name(path, compat_names=True), "portifolio_programacao_de_cnc")

    def test_scan_categorizes_numbered_folders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "10-engenharia").mkdir()
            (root / "PowerShell").mkdir()
            (root / "Atividade 01.docx").write_text("x", encoding="utf-8")

            scan = scan_directory(root, include_duplicates=False)
            by_name = {Path(item.source).name: item for item in scan.plan}

            self.assertEqual(by_name["10-engenharia"].action, "merge_dir")
            self.assertEqual(Path(by_name["10-engenharia"].destination).parts[-2:], ("recursos", "engenharia"))
            self.assertEqual(Path(by_name["PowerShell"].destination).parts[-3:-1], ("projetos", "automacao_codigo"))
            self.assertEqual(Path(by_name["Atividade 01.docx"].destination).parts[-3:-1], ("recursos", "estudos"))

    def test_repository_topics_use_compatible_names_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Python Scripts").mkdir()

            scan = scan_directory(root, include_duplicates=False)

            self.assertEqual(len(scan.plan), 1)
            self.assertEqual(Path(scan.plan[0].destination).parts[-2:], ("automacao_codigo", "python_scripts"))

    def test_plc_extensions_go_to_plc_project_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ladder = root / "Exercicio 5 de Ladder.stu"
            archive = root / "desafio do luizh.auto.sta"
            ladder.write_bytes(b"schneider project")
            archive.write_bytes(b"automation archive")

            scan = scan_directory(root, include_duplicates=False)
            by_name = {Path(item.source).name: item for item in scan.plan}

            self.assertEqual(by_name[ladder.name].category, "projetos/automacao_codigo/plc")
            self.assertEqual(Path(by_name[ladder.name].destination).name, "exercicio_5_de_ladder.stu")
            self.assertEqual(by_name[archive.name].category, "projetos/automacao_codigo/plc")
            self.assertEqual(scan.file_summary[".stu PLC"], 1)
            self.assertEqual(scan.file_summary[".sta PLC"], 1)

    def test_scan_reports_file_and_directory_composition_with_duplicates_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = root / "docs"
            images = root / "imagens"
            docs.mkdir()
            images.mkdir()
            (docs / "manual.pdf").write_text("a", encoding="utf-8")
            (docs / "manual copia.pdf").write_text("a", encoding="utf-8")
            (images / "foto.jpg").write_bytes(b"jpg")
            (root / "solto.txt").write_text("txt", encoding="utf-8")

            scan = scan_directory(root, include_duplicates=True)

            self.assertEqual(scan.file_summary[".pdf"], 2)
            self.assertEqual(scan.file_summary[".jpg"], 1)
            self.assertEqual(scan.file_summary[".txt"], 1)
            self.assertEqual(scan.directory_summary["docs"], 2)
            self.assertEqual(scan.directory_summary["imagens"], 1)
            self.assertEqual(scan.directory_summary["(raiz)"], 1)

    def test_pdf_padrao_empresa_is_separated_from_normal_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            normal = root / "manual.pdf"
            standard = root / "PO-05 - Politica de Industrializacao R01.pdf"
            normal.write_text("pdf comum", encoding="utf-8")
            standard.write_text("norma empresa", encoding="utf-8")

            scan = scan_directory(root, include_duplicates=False)
            standard_topic, reason = classify_entry(standard)

            self.assertEqual(scan.file_summary[".pdf"], 1)
            self.assertEqual(scan.file_summary[".pdf padrão empresa"], 1)
            self.assertEqual(standard_topic.directory, "areas/empresas_financeiro/padroes")
            self.assertIn("pdf padrao de empresa", reason)

    def test_pdf_livro_is_separated_from_normal_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            books = root / "1 - Para Ler" / "Base de Dados Para Ler"
            books.mkdir(parents=True)
            normal = root / "boleto.pdf"
            book = books / "Codigo Limpo - Completo PT.pdf"
            normal.write_text("pdf comum", encoding="utf-8")
            book.write_text("livro", encoding="utf-8")

            scan = scan_directory(root, include_duplicates=False)
            book_topic, reason = classify_entry(book)

            self.assertEqual(scan.file_summary[".pdf"], 1)
            self.assertEqual(scan.file_summary[".pdf livro"], 1)
            self.assertEqual(book_topic.directory, "recursos/leitura")
            self.assertIn("pdf livro", reason)

    def test_pdf_padrao_empresa_has_priority_over_book_terms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            standard = root / "Biblioteca" / "PADRAO RAMTECH - Manual Qualidade.pdf"
            standard.parent.mkdir()
            standard.write_text("padrao", encoding="utf-8")

            scan = scan_directory(root, include_duplicates=False)
            standard_topic, reason = classify_entry(standard)

            self.assertEqual(scan.file_summary[".pdf padrão empresa"], 1)
            self.assertNotIn(".pdf livro", scan.file_summary)
            self.assertEqual(standard_topic.directory, "areas/empresas_financeiro/padroes")
            self.assertIn("pdf padrao de empresa", reason)

    def test_document_cad_file_is_protected_unless_option_is_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cad_file = root / "base maquina.step"
            cad_file.write_bytes(b"step model")

            protected = scan_directory(root, include_duplicates=False)
            included = scan_directory(root, include_duplicates=False, include_cad=True)

            self.assertEqual(protected.plan, [])
            self.assertEqual(protected.file_summary[".step CAD"], 1)
            self.assertTrue(any("CAD em Documentos protegido" in item for item in protected.skipped))
            self.assertEqual(len(included.plan), 1)
            self.assertEqual(Path(included.plan[0].destination).parts[-3:-1], ("recursos", "engenharia"))
            self.assertEqual(included.plan[0].reason, "extensao: .step")

    def test_document_cad_folder_is_protected_unless_option_is_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cad_folder = root / "Cliente X"
            cad_folder.mkdir()
            (cad_folder / "conjunto.SLDASM").write_bytes(b"assembly")

            protected = scan_directory(root, include_duplicates=False)
            included = scan_directory(root, include_duplicates=False, include_cad=True)

            self.assertEqual(protected.plan, [])
            self.assertTrue(any("CAD em Documentos protegido" in item for item in protected.skipped))
            self.assertEqual(len(included.plan), 1)
            self.assertEqual(included.plan[0].category, "recursos/engenharia")
            self.assertEqual(included.plan[0].reason, "pasta com arquivos CAD")

    def test_document_solidworks_electrical_files_are_cad(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drawing = root / "folha01.ewg"
            drawing.write_bytes(b"electrical drawing")

            protected = scan_directory(root, include_duplicates=False)
            included = scan_directory(root, include_duplicates=False, include_cad=True)

            self.assertEqual(protected.plan, [])
            self.assertEqual(protected.file_summary[".ewg CAD"], 1)
            self.assertTrue(any("CAD em Documentos protegido" in item for item in protected.skipped))
            self.assertEqual(len(included.plan), 1)
            self.assertEqual(included.plan[0].category, "projetos/engenharia/SolidWorks-Electrical")

    def test_document_solidworks_electrical_archive_goes_to_specific_folder_when_included(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "FORNO CORNING-FINAL-completo.proj.tewzip"
            archive.write_bytes(b"electrical archive")

            protected = scan_directory(root, include_duplicates=False)
            included = scan_directory(root, include_duplicates=False, include_cad=True)

            self.assertEqual(protected.plan, [])
            self.assertTrue(any("CAD em Documentos protegido" in item for item in protected.skipped))
            self.assertEqual(len(included.plan), 1)
            self.assertEqual(included.plan[0].category, "projetos/engenharia/SolidWorks-Electrical")
            self.assertIn("SolidWorks Electrical", included.plan[0].reason)

    def test_document_solidworks_electrical_project_marker_protects_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "SolidWorks Electrical" / "Projeto A"
            project.mkdir(parents=True)
            (project / ".project").write_text("<projectDescription />", encoding="utf-8")
            (project / "assets" / "logo.jpg").parent.mkdir()
            (project / "assets" / "logo.jpg").write_bytes(b"asset")

            scan = scan_directory(root, include_duplicates=False)

            self.assertEqual(scan.plan, [])
            self.assertTrue(any("CAD em Documentos protegido" in item for item in scan.skipped))

    def test_document_cad_duplicates_only_enter_when_option_is_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "painel.dwg").write_bytes(b"same cad")
            (root / "painel - Copia.dwg").write_bytes(b"same cad")

            protected = find_duplicate_files(root, include_cad=False)
            included = find_duplicate_files(root, include_cad=True)

            self.assertEqual(protected.duplicates, [])
            self.assertEqual(protected.file_summary[".dwg CAD"], 2)
            self.assertTrue(any("arquivo(s) CAD" in item for item in protected.skipped))
            exact = [group for group in included.duplicates if group.kind == "exact"]
            self.assertEqual(len(exact), 1)
            self.assertEqual(len(exact[0].files), 2)

    def test_apply_plan_moves_without_deleting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "Python Scripts"
            source.mkdir()
            (source / "bot.py").write_text("print('ok')", encoding="utf-8")

            scan = scan_directory(root, include_duplicates=False)
            result = apply_plan(scan.plan, root)

            self.assertFalse(result.errors)
            self.assertFalse(source.exists())
            self.assertTrue((root / "projetos" / "automacao_codigo" / "python_scripts" / "bot.py").exists())

    def test_rollback_moves_returns_files_to_original_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "PowerShell"
            source.mkdir()
            (source / "deploy.ps1").write_text("Write-Host ok", encoding="utf-8")

            scan = scan_directory(root, include_duplicates=False)
            applied = apply_plan(scan.plan, root)
            rolled_back = rollback_moves(applied.moved, root)

            self.assertFalse(applied.errors)
            self.assertFalse(rolled_back.errors)
            self.assertTrue((source / "deploy.ps1").exists())

    def test_duplicate_quarantine_keeps_one_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("same", encoding="utf-8")
            copies = root / "copies"
            copies.mkdir()
            (copies / "a - Copia.txt").write_text("same", encoding="utf-8")

            duplicate_scan = find_duplicate_files(root)
            self.assertEqual(len(duplicate_scan.duplicates), 1)
            keeper = choose_duplicate_keeper(duplicate_scan.duplicates[0].files, root)
            self.assertEqual(Path(keeper).name, "a.txt")

            result = move_duplicates_to_quarantine(root, duplicate_scan.duplicates)
            self.assertFalse(result.errors)
            self.assertTrue((root / "a.txt").exists())
            self.assertEqual(len(result.moved), 1)
            self.assertTrue(Path(result.moved[0][1]).exists())

    def test_possible_duplicates_are_reported_but_not_moved_in_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "relatorio.pdf").write_text("versao curta", encoding="utf-8")
            (root / "relatorio (1).pdf").write_text("versao mais longa", encoding="utf-8")

            duplicate_scan = find_duplicate_files(root)
            possible = [group for group in duplicate_scan.duplicates if group.kind == "possible"]
            exact = [group for group in duplicate_scan.duplicates if group.kind == "exact"]

            self.assertEqual(exact, [])
            self.assertEqual(len(possible), 1)
            self.assertTrue(any("tamanhos diferentes" in item for item in possible[0].differences))
            self.assertTrue(any("hash nao aplicavel" in item for item in possible[0].differences))
            self.assertEqual(duplicate_hash_label(possible[0]), "nao aplic.")

            result = move_duplicates_to_quarantine(root, duplicate_scan.duplicates)
            self.assertEqual(result.moved, [])
            self.assertEqual(len(result.skipped), 1)
            self.assertTrue((root / "relatorio.pdf").exists())
            self.assertTrue((root / "relatorio (1).pdf").exists())

    def test_same_common_name_without_copy_marker_is_not_possible_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "proj-a"
            second = root / "proj-b"
            first.mkdir()
            second.mkdir()
            (first / "README.md").write_text("a", encoding="utf-8")
            (second / "README.md").write_text("b", encoding="utf-8")

            duplicate_scan = find_duplicate_files(root)

            self.assertEqual(duplicate_scan.duplicates, [])

    def test_program_managed_folder_is_protected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = root / "Battlefield 4"
            game.mkdir()
            (game / "settings.dat").write_text("x", encoding="utf-8")
            office = root / "6 - Custom Office Templates"
            office.mkdir()
            (root / "PowerShell").mkdir()

            scan = scan_directory(root, include_duplicates=False)
            planned_names = {Path(item.source).name for item in scan.plan}

            self.assertNotIn("Battlefield 4", planned_names)
            self.assertNotIn("6 - Custom Office Templates", planned_names)
            self.assertIn("PowerShell", planned_names)
            self.assertTrue(any("pasta gerenciada por programa" in item for item in scan.skipped))

    def test_projects_cad_root_is_not_scanned_as_documents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "organizar").mkdir()
            (root / "projetos").mkdir()

            scan = scan_directory(root, include_duplicates=False)

            self.assertEqual(scan.plan, [])
            self.assertTrue(any("Projetos/CAD" in item for item in scan.errors))

    def test_internal_state_dirs_are_silent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "_arruma_dir").mkdir()
            (root / "_duplicados").mkdir()

            scan = scan_directory(root, include_duplicates=False)

            self.assertEqual(scan.skipped, [])

    def test_large_files_are_not_hashed_in_fast_duplicate_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "grande.bin").write_bytes(b"x" * (1024 * 1024 + 1))

            duplicate_scan = find_duplicate_files(root, max_file_size_mb=1)

            self.assertTrue(any("nao foram hasheados" in item for item in duplicate_scan.skipped))

    def test_exact_duplicate_without_copy_marker_is_kept_for_manual_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "docs"
            second = root / "backup"
            first.mkdir()
            second.mkdir()
            (first / "manual.pdf").write_text("same", encoding="utf-8")
            (second / "manual.pdf").write_text("same", encoding="utf-8")

            duplicate_scan = find_duplicate_files(root)
            self.assertEqual(len(duplicate_scan.duplicates), 1)
            self.assertEqual(duplicate_scan.duplicates[0].kind, "exact")

            result = move_duplicates_to_quarantine(root, duplicate_scan.duplicates)
            self.assertEqual(result.moved, [])
            self.assertEqual(len(result.skipped), 1)
            self.assertTrue((first / "manual.pdf").exists())
            self.assertTrue((second / "manual.pdf").exists())


if __name__ == "__main__":
    unittest.main()
