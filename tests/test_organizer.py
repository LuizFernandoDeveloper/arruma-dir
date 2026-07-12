from __future__ import annotations

import tempfile
import unittest
import stat
from pathlib import Path

from arruma_dir.organizer import (
    apply_plan,
    choose_duplicate_keeper,
    classify_entry,
    clean_leaf_name,
    duplicate_hash_label,
    find_duplicate_files,
    learn_directory_profile,
    move_duplicates_to_quarantine,
    rollback_moves,
    scan_directory,
    scan_name_standardization,
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
            self.assertEqual(clean_leaf_name(path, compat_names=True), "portifolio-programacao-de-cnc")
            dated = Path(tmp) / "02-05-2025.ods"
            dated.write_text("data", encoding="utf-8")
            self.assertEqual(clean_leaf_name(dated, compat_names=True), "02-05-2025.ods")

    def test_standardization_removes_number_prefix_and_spaces_from_common_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "1 - Name With Spaces"
            source.mkdir()
            (source / "Arquivo Interno.txt").write_text("x", encoding="utf-8")

            scan = scan_name_standardization(root)
            by_source = {Path(item.source).name: item for item in scan.plan}

            self.assertIn(source.name, by_source)
            self.assertEqual(Path(by_source[source.name].destination).name, "001-name-with-spaces")

            result = apply_plan(scan.plan, root)

            self.assertFalse(result.errors)
            self.assertFalse(source.exists())
            self.assertTrue((root / "001-name-with-spaces" / "arquivo-interno.txt").exists())

    def test_name_standardization_renames_case_only_folders_inside_user_areas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marketplaces = root / "areas" / "empresas_financeiro" / "Marketplaces"
            mecatronica = root / "areas" / "empresas_financeiro" / "Mecatronica"
            marketplaces.mkdir(parents=True)
            mecatronica.mkdir()

            scan = scan_name_standardization(root)
            destinations = {Path(item.destination).name for item in scan.plan}

            self.assertIn("marketplaces", destinations)
            self.assertIn("mecatronica", destinations)

            result = apply_plan(scan.plan, root)

            self.assertFalse(result.errors)
            final_names = {item.name for item in (root / "areas" / "empresas_financeiro").iterdir()}
            self.assertNotIn("Marketplaces", final_names)
            self.assertNotIn("Mecatronica", final_names)
            self.assertIn("marketplaces", final_names)
            self.assertIn("mecatronica", final_names)

    def test_case_only_standardization_can_be_rolled_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "areas" / "empresas_financeiro" / "Marketplaces"
            source.mkdir(parents=True)

            scan = scan_name_standardization(root)
            applied = apply_plan(scan.plan, root)
            rolled_back = rollback_moves(applied.moved, root)

            self.assertFalse(applied.errors)
            self.assertFalse(rolled_back.errors)
            final_names = {item.name for item in (root / "areas" / "empresas_financeiro").iterdir()}
            self.assertIn("Marketplaces", final_names)

    def test_name_standardization_preserves_default_program_folders_and_contents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            program_folders = [
                root / "6 - Custom Office Templates",
                root / "Acade 2026",
                root / "Battlefield 4",
                root / "Blocos de Anotações do OneNote",
                root / "CATIAComposer",
                root / "Factory IO",
                root / "FluidSIM Hydraulics",
                root / "Gravações de som",
                root / "MATLAB",
                root / "Minhas Formas",
                root / "Modelos Personalizados do Office",
                root / "OneNote Notebooks",
            ]
            for folder in program_folders:
                (folder / "Child Folder With Spaces").mkdir(parents=True)

            scan = scan_name_standardization(root)
            planned_sources = {Path(item.source) for item in scan.plan}

            self.assertEqual(planned_sources, set())

    def test_learns_numbered_area_root_from_existing_documents_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "__Minhas-areas" / "001-saude").mkdir(parents=True)
            (root / "__Minhas-areas" / "002-carreira").mkdir()
            (root / "__Minhas-areas" / "004-empresas_financeiro" / "padroes").mkdir(parents=True)
            (root / "__Minhas-areas" / "005-pessoal").mkdir()
            (root / "_entrada" / "revisar").mkdir(parents=True)

            profile = learn_directory_profile(root)

            self.assertEqual(profile.area_root, Path("__Minhas-areas"))
            self.assertEqual(profile.area_children["saude"], Path("__Minhas-areas") / "001-saude")
            self.assertEqual(
                profile.area_children["empresas financeiro"],
                Path("__Minhas-areas") / "004-empresas_financeiro",
            )
            self.assertEqual(profile.entry_root, Path("_entrada"))

    def test_scan_uses_learned_area_root_for_new_area_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "__Minhas-areas" / "001-saude").mkdir(parents=True)
            (root / "__Minhas-areas" / "004-empresas_financeiro" / "padroes").mkdir(parents=True)
            contract = root / "Contrato empresa.docx"
            exam = root / "Exame saude.pdf"
            contract.write_text("empresa", encoding="utf-8")
            exam.write_text("saude", encoding="utf-8")

            scan = scan_directory(root, include_duplicates=False)
            by_name = {Path(item.source).name: item for item in scan.plan}

            self.assertEqual(
                Path(by_name[contract.name].destination).parent,
                root / "__Minhas-areas" / "004-empresas_financeiro",
            )
            self.assertEqual(
                Path(by_name[exam.name].destination).parent,
                root / "__Minhas-areas" / "001-saude",
            )

    def test_scan_uses_learned_entry_root_for_review_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "_entrada" / "revisar").mkdir(parents=True)
            unknown = root / "coisa-sem-regra.bin"
            unknown.write_bytes(b"x")

            scan = scan_directory(root, include_duplicates=False)

            self.assertEqual(len(scan.plan), 1)
            self.assertEqual(Path(scan.plan[0].destination).parent, root / "_entrada" / "revisar")

    def test_standardization_preserves_learned_area_root_but_cleans_children(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root_area = root / "__Minhas-areas"
            company = root_area / "004-empresas_financeiro"
            marketplaces = company / "Marketplaces"
            mecatronica = company / "Mecatronica"
            marketplaces.mkdir(parents=True)
            mecatronica.mkdir()
            (root_area / "001-saude").mkdir()
            (root_area / "002-carreira").mkdir()
            (root_area / "005-pessoal").mkdir()

            scan = scan_name_standardization(root)
            by_source = {Path(item.source).name: item for item in scan.plan}

            self.assertNotIn("__Minhas-areas", by_source)
            self.assertNotIn("004-empresas_financeiro", by_source)
            self.assertEqual(Path(by_source["Marketplaces"].destination).name, "marketplaces")
            self.assertEqual(Path(by_source["Mecatronica"].destination).name, "mecatronica")

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
            self.assertEqual(Path(scan.plan[0].destination).parts[-2:], ("automacao_codigo", "python-scripts"))

    def test_name_standardization_renames_common_folders_but_preserves_business_standards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            common = root / "Fotos Cliente Final"
            common.mkdir()
            ramtech = root / "P20051-792589 - BEM BRASIL"
            ramtech.mkdir()
            opcao = root / "047-007-000-REV00 - MONTAGEM DO FORNO"
            opcao.mkdir()

            scan = scan_name_standardization(root)
            by_source = {Path(item.source).name: item for item in scan.plan}

            self.assertIn(common.name, by_source)
            self.assertEqual(Path(by_source[common.name].destination).name, "fotos-cliente-final")
            self.assertNotIn(ramtech.name, by_source)
            self.assertNotIn(opcao.name, by_source)
            self.assertTrue(any("Ramtech/Opcao" in item for item in scan.skipped))

    def test_name_standardization_merges_existing_standard_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wrong = root / "Fotos Cliente Final"
            correct = root / "fotos-cliente-final"
            wrong.mkdir()
            correct.mkdir()
            (wrong / "Imagem Nova.JPG").write_bytes(b"nova")
            (correct / "existente.txt").write_text("ok", encoding="utf-8")

            scan = scan_name_standardization(root)
            merge_items = [item for item in scan.plan if item.source == str(wrong)]

            self.assertEqual(len(merge_items), 1)
            self.assertEqual(merge_items[0].action, "merge_dir")
            result = apply_plan(scan.plan, root)

            self.assertFalse(result.errors)
            self.assertFalse(wrong.exists())
            self.assertTrue((correct / "imagem-nova.jpg").exists())
            self.assertTrue((correct / "existente.txt").exists())
            self.assertFalse((root / "fotos-cliente-final (2)").exists())

    def test_name_standardization_preserves_arruma_standard_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            standard_company = root / "areas" / "empresas_financeiro" / "padroes"
            standard_plc = root / "projetos" / "automacao_codigo" / "plc"
            wrong_inside = root / "areas" / "empresas_financeiro" / "lançamento  de  produtos  e empressas"
            standard_company.mkdir(parents=True)
            standard_plc.mkdir(parents=True)
            wrong_inside.mkdir()

            scan = scan_name_standardization(root)
            sources = {Path(item.source).name: item for item in scan.plan}

            self.assertNotIn("areas", sources)
            self.assertNotIn("empresas_financeiro", sources)
            self.assertNotIn("automacao_codigo", sources)
            self.assertNotIn("plc", sources)
            self.assertIn(wrong_inside.name, sources)
            self.assertEqual(Path(sources[wrong_inside.name].destination).name, "lancamento-de-produtos-e-empressas")

    def test_name_standardization_renames_repository_folder_without_entering_contents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "projetos" / "automacao_codigo" / "Meu Repo"
            (repo / ".git" / "refs").mkdir(parents=True)
            (repo / "node_modules" / "Pacote Ruim").mkdir(parents=True)
            (repo / "target" / "Debug Build").mkdir(parents=True)

            scan = scan_name_standardization(root)
            sources = {Path(item.source).name: item for item in scan.plan}

            self.assertIn("Meu Repo", sources)
            self.assertEqual(Path(sources["Meu Repo"].destination).name, "meu-repo")
            self.assertNotIn("Pacote Ruim", sources)
            self.assertNotIn("Debug Build", sources)
            self.assertTrue(any("conteudo de projeto/repositorio preservado" in item for item in scan.skipped))

    def test_name_standardization_skips_code_project_contents_without_git(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "recursos" / "engenharia" / "Projeto Web"
            app = project / "src" / "app"
            app.mkdir(parents=True)
            (project / "package.json").write_text("{}", encoding="utf-8")
            (app / "app.spec.ts").write_text("test", encoding="utf-8")

            scan = scan_name_standardization(root)
            sources = {Path(item.source).name: item for item in scan.plan}

            self.assertIn("Projeto Web", sources)
            self.assertEqual(Path(sources["Projeto Web"].destination).name, "projeto-web")
            self.assertNotIn("app.spec.ts", sources)
            self.assertTrue(any("conteudo de projeto/repositorio preservado" in item for item in scan.skipped))

    def test_name_standardization_preserves_dotfiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".editorconfig").write_text("root = true", encoding="utf-8")
            (root / ".gitignore").write_text("__pycache__/", encoding="utf-8")

            scan = scan_name_standardization(root)
            sources = {Path(item.source).name for item in scan.plan}

            self.assertNotIn(".editorconfig", sources)
            self.assertNotIn(".gitignore", sources)

    def test_apply_plan_removes_old_topic_folders_after_merge_with_windows_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = {
                "10-engenharia": ("recursos", "engenharia", "nota.txt"),
                "7 -  Estudos": ("recursos", "estudos", "aula.pdf"),
                "9 - Empresas": ("areas", "empresas_financeiro", "boleto.pdf"),
                "plc": ("projetos", "automacao_codigo", "plc", "programa.stu"),
            }
            for source_name, parts in cases.items():
                source = root / source_name
                source.mkdir()
                (source / parts[-1]).write_text("conteudo", encoding="utf-8")
                (source / "desktop.ini").write_text("[ViewState]", encoding="utf-8")

            scan = scan_directory(root, include_duplicates=False)
            result = apply_plan(scan.plan, root)

            self.assertFalse(result.errors)
            for source_name, parts in cases.items():
                self.assertFalse((root / source_name).exists())
                self.assertTrue((root / Path(*parts)).exists())

    def test_apply_plan_merge_dir_dry_run_keeps_source_and_destination_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "10-engenharia"
            source.mkdir()
            (source / "nota.txt").write_text("conteudo", encoding="utf-8")

            scan = scan_directory(root, include_duplicates=False)
            result = apply_plan(scan.plan, root, dry_run=True)

            self.assertFalse(result.errors)
            self.assertTrue(source.exists())
            self.assertTrue((source / "nota.txt").exists())
            self.assertFalse((root / "recursos" / "engenharia").exists())
            self.assertEqual(len(result.moved), 1)

    def test_apply_plan_merge_dir_merges_nested_existing_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "10-engenharia"
            nested = source / "Projetos Antigos"
            target_nested = root / "recursos" / "engenharia" / "projetos-antigos"
            nested.mkdir(parents=True)
            target_nested.mkdir(parents=True)
            (nested / "Novo Arquivo.txt").write_text("novo", encoding="utf-8")
            (target_nested / "existente.txt").write_text("ok", encoding="utf-8")

            scan = scan_directory(root, include_duplicates=False)
            result = apply_plan(scan.plan, root)

            self.assertFalse(result.errors)
            self.assertFalse(source.exists())
            self.assertTrue((target_nested / "novo-arquivo.txt").exists())
            self.assertTrue((target_nested / "existente.txt").exists())

    def test_apply_plan_merge_dir_removes_readonly_windows_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "10-engenharia"
            source.mkdir()
            metadata = source / "desktop.ini"
            metadata.write_text("[ViewState]", encoding="utf-8")
            metadata.chmod(stat.S_IREAD)
            (source / "nota.txt").write_text("conteudo", encoding="utf-8")

            try:
                scan = scan_directory(root, include_duplicates=False)
                result = apply_plan(scan.plan, root)

                self.assertFalse(result.errors)
                self.assertFalse(source.exists())
                self.assertTrue((root / "recursos" / "engenharia" / "nota.txt").exists())
            finally:
                if metadata.exists():
                    metadata.chmod(stat.S_IWRITE | stat.S_IREAD)

    def test_apply_plan_reports_leftover_items_after_merge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "10-engenharia"
            temp_dir = source / ".tmp-cache"
            temp_dir.mkdir(parents=True)
            (temp_dir / "lock.tmp").write_text("travado", encoding="utf-8")
            (source / "nota.txt").write_text("conteudo", encoding="utf-8")

            scan = scan_directory(root, include_duplicates=False)
            result = apply_plan(scan.plan, root)

            self.assertFalse(result.errors)
            self.assertTrue(source.exists())
            self.assertTrue((root / "recursos" / "engenharia" / "nota.txt").exists())
            self.assertTrue(any(".tmp-cache" in item for item in result.skipped))

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
            self.assertEqual(Path(by_name[ladder.name].destination).name, "exercicio-5-de-ladder.stu")
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
            self.assertTrue((root / "projetos" / "automacao_codigo" / "python-scripts" / "bot.py").exists())

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

    def test_same_size_copy_name_with_different_hash_is_review_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = root / "relatorio.pdf"
            copy = root / "relatorio copia.pdf"
            original.write_bytes(b"ab")
            copy.write_bytes(b"cd")

            duplicate_scan = find_duplicate_files(root)
            possible = [group for group in duplicate_scan.duplicates if group.kind == "possible"]
            exact = [group for group in duplicate_scan.duplicates if group.kind == "exact"]

            self.assertEqual(exact, [])
            self.assertEqual(len(possible), 1)
            self.assertTrue(any("SHA-256 diferente" in item for item in possible[0].differences))
            self.assertEqual(duplicate_hash_label(possible[0]), "SHA dif.")

            result = move_duplicates_to_quarantine(root, duplicate_scan.duplicates)

            self.assertEqual(result.moved, [])
            self.assertEqual(len(result.skipped), 1)
            self.assertTrue(original.exists())
            self.assertTrue(copy.exists())

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

    def test_exact_duplicate_without_copy_marker_is_moved_when_hash_matches(self) -> None:
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
            keeper = Path(choose_duplicate_keeper(duplicate_scan.duplicates[0].files, root))
            moved_source = first / "manual.pdf" if keeper == second / "manual.pdf" else second / "manual.pdf"

            result = move_duplicates_to_quarantine(root, duplicate_scan.duplicates)
            self.assertFalse(result.errors)
            self.assertEqual(result.skipped, [])
            self.assertEqual(len(result.moved), 1)
            self.assertTrue(keeper.exists())
            self.assertFalse(moved_source.exists())
            self.assertTrue(Path(result.moved[0][1]).exists())

    def test_duplicate_quarantine_preserves_file_extension_in_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "manual.pdf").write_bytes(b"same")
            (root / "manual copia.pdf").write_bytes(b"same")

            duplicate_scan = find_duplicate_files(root)
            result = move_duplicates_to_quarantine(root, duplicate_scan.duplicates, dry_run=True)

            self.assertEqual(len(result.moved), 1)
            self.assertEqual(Path(result.moved[0][1]).suffix, ".pdf")
            self.assertTrue((root / "manual.pdf").exists())
            self.assertTrue((root / "manual copia.pdf").exists())

    def test_duplicate_quarantine_collision_keeps_existing_quarantine_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "manual.pdf").write_bytes(b"same")
            (root / "manual copia.pdf").write_bytes(b"same")

            duplicate_scan = find_duplicate_files(root)
            dry_run = move_duplicates_to_quarantine(root, duplicate_scan.duplicates, dry_run=True)
            first_target = Path(dry_run.moved[0][1])
            first_target.parent.mkdir(parents=True)
            first_target.write_text("arquivo ja estava aqui", encoding="utf-8")

            result = move_duplicates_to_quarantine(root, duplicate_scan.duplicates)

            self.assertFalse(result.errors)
            self.assertEqual(len(result.moved), 1)
            final_target = Path(result.moved[0][1])
            self.assertNotEqual(final_target, first_target)
            self.assertEqual(final_target.suffix, ".pdf")
            self.assertTrue(final_target.exists())
            self.assertEqual(first_target.read_text(encoding="utf-8"), "arquivo ja estava aqui")


if __name__ == "__main__":
    unittest.main()
