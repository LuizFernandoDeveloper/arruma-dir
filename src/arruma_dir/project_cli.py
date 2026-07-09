from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from arruma_dir.hardware import detect_hardware, normalize_performance_mode
from arruma_dir.logging_utils import close_logger, create_operation_logger
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
    logger.info("comando=%s", operation)
    logger.info("raiz=%s", root)
    return logger, log_path


def resolve_workers(args: argparse.Namespace) -> tuple[int, str]:
    mode = normalize_performance_mode(getattr(args, "performance", "balanced"))
    profile = detect_hardware()
    workers = getattr(args, "workers", None) or profile.workers_for(mode)
    return max(1, workers), profile.summary(mode)


def log_project_report(logger: logging.Logger | None, report: ProjectReport) -> None:
    if logger is None:
        return
    logger.info("gerado_em=%s", report.generated_at)
    for key, value in report.stats.items():
        logger.info("stat.%s=%s", key, value)
    for index, item in enumerate(report.organization, start=1):
        logger.info(
            "organizacao[%04d] action=%s source=%s destination=%s reason=%s",
            index,
            item.action,
            item.source,
            item.destination,
            item.reason,
        )
    for index, item in enumerate(report.duplicates, start=1):
        logger.info(
            "duplicata[%04d] size=%s sha256=%s source=%s keeper=%s destination=%s reason=%s",
            index,
            item.size,
            item.sha256,
            item.source,
            item.keeper,
            item.destination,
            item.reason,
        )
    for index, item in enumerate(report.external_candidates, start=1):
        logger.info(
            "externo[%04d] score=%s drive=%s source=%s destination=%s reasons=%s size=%s",
            index,
            item.score,
            item.drive,
            item.source,
            item.destination,
            "; ".join(item.reasons),
            item.size,
        )
    for item in report.warnings:
        logger.warning("%s", item)
    for item in report.errors:
        logger.error("%s", item)


def log_project_apply(logger: logging.Logger | None, result: ProjectApplyResult) -> None:
    if logger is None:
        return
    logger.info(
        "movidos=%s copiados=%s ignorados=%s erros=%s",
        len(result["moved"]),
        len(result["copied"]),
        len(result["skipped"]),
        len(result["errors"]),
    )
    for key in ("moved", "copied"):
        for item in result[key]:
            logger.info("%s %s", key, item)
    for item in result["skipped"]:
        logger.warning("%s", item)
    for item in result["errors"]:
        logger.error("%s", item)


def print_project_report_details(report: ProjectReport) -> None:
    for item in report.organization:
        print(f"Plano: {item.action} | {item.source} -> {item.destination} | {item.reason}")
    for item in report.duplicates:
        print(f"Duplicata: {item.source} -> {item.destination} | principal={item.keeper}")
    for item in report.external_candidates:
        print(f"HD externo: score={item.score} | {item.source} -> {item.destination} | {', '.join(item.reasons)}")
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
            logger.info("hardware_profile=%s", hardware_summary)
            logger.info(
                "opcoes external=%s drives=%s include_fixed_external=%s min_external_score=%s max_files=%s max_hash_size_mb=%s no_hash=%s include_cad_duplicates=%s",
                args.external,
                ",".join(args.external_drive),
                args.include_fixed_external,
                args.min_external_score,
                args.max_files,
                args.max_hash_size_mb,
                args.no_hash,
                args.include_cad_duplicates,
            )
        report = scan_projects(
            root,
            external=args.external,
            external_drives=drives or None,
            include_fixed_external=args.include_fixed_external,
            min_external_score=args.min_external_score,
            max_files=args.max_files,
            max_hash_size_mb=args.max_hash_size_mb,
            no_hash=args.no_hash,
            include_cad_duplicates=args.include_cad_duplicates,
            hash_workers=workers,
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
                "report=%s organize=%s duplicates=%s import_external=%s yes=%s dry_run=%s",
                args.report,
                args.organize,
                args.duplicates,
                args.import_external,
                args.yes,
                not args.yes,
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
