from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arruma_dir.organizer import (
    apply_plan,
    choose_duplicate_keeper,
    clean_leaf_name,
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
            self.assertTrue((root / "projetos" / "automacao_codigo" / "Python Scripts" / "bot.py").exists())

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
