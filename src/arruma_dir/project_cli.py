from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from arruma_dir.hardware import detect_hardware, normalize_performance_mode
from arruma_dir.logging_utils import close_logger, create_operation_logger, format_log_event
from arruma_dir.project_organizer import (
    DEFAULT_ROOT,
    REPORTS_DIR,
    ProjectApplyResult,
    ProjectReport,
    apply_report,
    create_opcao_template,
    create_project_template,
    load_report,
    scan_projects,
    state_path,
    write_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Organiza F:\\projetos com padrao Ramtech/Macrotec/Opcao.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="gera relatorio e plano sem mover nada")
    scan.add_argument("--root", default=str(DEFAULT_ROOT))
    scan.add_argument("--output-dir", default=None)
    scan.add_argument("--external", action="store_true", help="vasculha drives externos/removiveis")
    scan.add_argument("--external-drive", action="append", default=[], help="drive explicito, ex: G:\\")
    scan.add_argument(
        "--populate-base",
        action="store_true",
        help="popular base: copia somente candidatos ausentes para destinos dentro de projetos",
    )
    scan.add_argument("--include-fixed-external", action="store_true", help="inclui drives fixos nao-C alem de removiveis")
    scan.add_argument("--min-external-score", type=int, default=7)
    scan.add_argument("--max-files", type=int, default=None)
    scan.add_argument("--max-hash-size-mb", type=int, default=2048)
    scan.add_argument("--no-hash", action="store_true", help="nao calcula duplicados")
    scan.add_argument(
        "--include-cad-duplicates",
        action="store_true",
        help="inclui arquivos CAD na quarentena de duplicatas; use com cuidado",
    )
    scan.add_argument("--verbose", action="store_true", help="mostra detalhes completos tambem no terminal")
    scan.add_argument("--no-log-file", action="store_true", help="nao gera arquivo .log da execucao")
    scan.add_argument("--performance", choices=["safe", "balanced", "max"], default="balanced", help="perfil de desempenho para tarefas de hash")
    scan.add_argument("--workers", type=int, default=None, help="numero de workers para hash (sobrepoe --performance)")

    apply = subparsers.add_parser("apply", help="aplica partes de um relatorio")
    apply.add_argument("--report", required=True)
    apply.add_argument("--organize", action="store_true")
    apply.add_argument("--duplicates", action="store_true")
    apply.add_argument("--import-external", action="store_true")
    apply.add_argument("--yes", action="store_true", help="executa de verdade; sem isso e simulacao")
    apply.add_argument("--verbose", action="store_true", help="mostra detalhes completos tambem no terminal")
    apply.add_argument("--no-log-file", action="store_true", help="nao gera arquivo .log da execucao")

    template = subparsers.add_parser("template", help="cria estrutura padrao de projeto Ramtech")
    template.add_argument("name", help="ex: P20051-792589 - BEM BRASIL")
    template.add_argument("--root", default=str(DEFAULT_ROOT))
    template.add_argument("--yes", action="store_true")

    template_opcao = subparsers.add_parser("template-opcao", help="cria estrutura padrao de projeto mecanico Opcao")
    template_opcao.add_argument("name", help="ex: 047-007-000-REV00 - MONTAGEM DO FORNO")
    template_opcao.add_argument("--root", default=str(DEFAULT_ROOT))
    template_opcao.add_argument("--yes", action="store_true")

    return parser


def make_project_logger(args: argparse.Namespace, root: str | Path, operation: str) -> tuple[logging.Logger | None, Path | None]:
    if getattr(args, "no_log_file", False):
        return None, None
    logger, log_path = create_operation_logger(root, mode="projects", operation=operation, console=getattr(args, "verbose", False))
    logger.info(format_log_event("project_cli.command", command=operation, root=root))
    return logger, log_path


def resolve_workers(args: argparse.Namespace) -> tuple[int, str]:
    mode = normalize_performance_mode(getattr(args, "performance", "balanced"))
    profile = detect_hardware()
    workers = getattr(args, "workers", None) or profile.workers_for(mode)
    return max(1, workers), profile.summary(mode)


def log_project_report(logger: logging.Logger | None, report: ProjectReport) -> None:
    if logger is None:
        return
    logger.info(format_log_event("project_report.generated", root=report.root, generated_at=report.generated_at))
    for key, value in report.stats.items():
        logger.info(format_log_event("project_report.stat", name=key, value=value))
    for index, item in enumerate(report.organization, start=1):
        logger.info(
            format_log_event(
                "project.organization",
                index=index,
                action=item.action,
                source=item.source,
                destination=item.destination,
                reason=item.reason,
            )
        )
    for index, item in enumerate(report.duplicates, start=1):
        logger.info(
            format_log_event(
                "project.duplicate",
                index=index,
                size=item.size,
                sha256=item.sha256,
                source=item.source,
                keeper=item.keeper,
                remove=item.source,
                destination=item.destination,
                reason=item.reason,
            )
        )
    for index, item in enumerate(report.external_candidates, start=1):
        logger.info(
            format_log_event(
                "project.external_candidate",
                index=index,
                score=item.score,
                drive=item.drive,
                source=item.source,
                destination=item.destination,
                reasons=item.reasons,
                size=item.size,
                sha256=item.sha256,
                duplicate_of=item.duplicate_of,
                decision=item.decision,
            )
        )
    for item in report.warnings:
        logger.warning(format_log_event("project.warning", message=item))
    for item in report.errors:
        logger.error(format_log_event("project.error", message=item))


def log_project_apply(logger: logging.Logger | None, result: ProjectApplyResult) -> None:
    if logger is None:
        return
    logger.info(
        format_log_event(
            "project_apply.summary",
            moved=len(result["moved"]),
            copied=len(result["copied"]),
            skipped=len(result["skipped"]),
            errors=len(result["errors"]),
        )
    )
    for key in ("moved", "copied"):
        for item in result[key]:
            logger.info(format_log_event("project_apply.item", kind=key, value=item))
    for item in result["skipped"]:
        logger.warning(format_log_event("project_apply.skipped", message=item))
    for item in result["errors"]:
        logger.error(format_log_event("project_apply.error", message=item))


def print_project_report_details(report: ProjectReport) -> None:
    for item in report.organization:
        print(f"Plano: {item.action} | {item.source} -> {item.destination} | {item.reason}")
    for item in report.duplicates:
        print(f"Duplicata: {item.source} -> {item.destination} | principal={item.keeper}")
    for item in report.external_candidates:
        print(
            f"HD externo: {item.decision} | score={item.score} | "
            f"{item.source} -> {item.destination} | {', '.join(item.reasons)}"
        )
    for item in report.warnings:
        print(f"Aviso: {item}")
    for item in report.errors:
        print(f"Erro: {item}", file=sys.stderr)


def print_result(result: ProjectApplyResult, *, limit: int | None = 30) -> None:
    for key in ("moved", "copied", "skipped", "errors"):
        values = result[key]
        print(f"{key}: {len(values)}")
        shown = values if limit is None else values[:limit]
        for item in shown:
            print(f"  {item}")
        if limit is not None and len(values) > limit:
            print(f"  ... mais {len(values) - limit}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "scan":
        root = Path(args.root)
        output_dir = Path(args.output_dir) if args.output_dir else state_path(root, REPORTS_DIR)
        drives = [Path(value) for value in args.external_drive]
        logger, log_path = make_project_logger(args, root, "scan")
        workers, hardware_summary = resolve_workers(args)
        if logger:
            logger.info(format_log_event("project_cli.hardware", profile=hardware_summary))
            logger.info(
                format_log_event(
                    "project_cli.scan_options",
                    external=args.external,
                    drives=args.external_drive,
                    populate_base=args.populate_base,
                    include_fixed_external=args.include_fixed_external,
                    min_external_score=args.min_external_score,
                    max_files=args.max_files,
                    max_hash_size_mb=args.max_hash_size_mb,
                    no_hash=args.no_hash,
                    include_cad_duplicates=args.include_cad_duplicates,
                )
            )
        report = scan_projects(
            root,
            external=args.external or args.populate_base,
            external_drives=drives or None,
            include_fixed_external=args.include_fixed_external,
            min_external_score=args.min_external_score,
            max_files=args.max_files,
            max_hash_size_mb=args.max_hash_size_mb,
            no_hash=args.no_hash,
            include_cad_duplicates=args.include_cad_duplicates,
            hash_workers=workers,
            populate_base=args.populate_base,
        )
        log_project_report(logger, report)
        json_path, csv_path, md_path = write_report(report, output_dir)
        print(f"Raiz: {report.root}")
        for key, value in report.stats.items():
            print(f"{key}: {value}")
        if args.verbose:
            print_project_report_details(report)
        print(f"JSON: {json_path}")
        print(f"CSV: {csv_path}")
        print(f"Resumo: {md_path}")
        if log_path:
            print(f"Log completo: {log_path}")
        if logger:
            close_logger(logger)
        return 1 if report.errors else 0

    if args.command == "apply":
        if not (args.organize or args.duplicates or args.import_external):
            parser.error("escolha pelo menos uma acao: --organize, --duplicates ou --import-external")
        report = load_report(Path(args.report))
        logger, log_path = make_project_logger(args, report.root, "apply")
        if logger:
            logger.info(
                format_log_event(
                    "project_cli.apply_options",
                    report=args.report,
                    organize=args.organize,
                    duplicates=args.duplicates,
                    import_external=args.import_external,
                    yes=args.yes,
                    dry_run=not args.yes,
                )
            )
        result = apply_report(
            report,
            organize=args.organize,
            duplicates=args.duplicates,
            import_external=args.import_external,
            yes=args.yes,
        )
        log_project_apply(logger, result)
        if not args.yes:
            print("SIMULACAO: use --yes para executar de verdade.")
        print_result(result, limit=None if args.verbose else 30)
        if log_path:
            print(f"Log completo: {log_path}")
        if logger:
            close_logger(logger)
        return 1 if result["errors"] else 0

    if args.command == "template":
        root = Path(args.root)
        created = create_project_template(root, args.name, yes=args.yes)
        if not args.yes:
            print("SIMULACAO: use --yes para criar as pastas.")
        for item in created:
            print(item)
        return 0

    if args.command == "template-opcao":
        root = Path(args.root)
        created = create_opcao_template(root, args.name, yes=args.yes)
        if not args.yes:
            print("SIMULACAO: use --yes para criar as pastas.")
        for item in created:
            print(item)
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
