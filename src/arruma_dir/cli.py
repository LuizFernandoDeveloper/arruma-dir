from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from arruma_dir.hardware import detect_hardware, normalize_performance_mode
from arruma_dir.logging_utils import close_logger, create_operation_logger
from arruma_dir.organizer import (
    ApplyResult,
    ScanResult,
    apply_plan,
    default_documents_path,
    load_plan_json,
    move_duplicates_to_quarantine,
    scan_directory,
    write_plan_csv,
    write_scan_json,
)


def add_log_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--verbose", action="store_true", help="mostra detalhes completos tambem no terminal")
    parser.add_argument("--no-log-file", action="store_true", help="nao gera arquivo .log da execucao")


def add_performance_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--performance",
        choices=("safe", "balanced", "max"),
        default="balanced",
        help="perfil de uso do hardware para hash de duplicatas",
    )
    parser.add_argument("--workers", type=int, default=None, help="numero de threads de hash; sobrescreve --performance")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arruma-dir",
        description="Organiza diretorios por topicos com pre-visualizacao segura.",
    )
    subparsers = parser.add_subparsers(dest="command")

    scan = subparsers.add_parser("scan", help="gera uma pre-visualizacao sem mover arquivos")
    scan.add_argument("path", nargs="?", default=str(default_documents_path()))
    scan.add_argument("--compat-names", action="store_true", help="usa nomes sem acentos e sem espacos")
    scan.add_argument("--no-duplicates", action="store_true", help="nao calcula arquivos repetidos")
    scan.add_argument(
        "--include-cad",
        action="store_true",
        help="inclui arquivos e pastas CAD de Documentos na organizacao e nas duplicatas",
    )
    scan.add_argument("--duplicate-time-limit", type=float, default=90.0, help="segundos para busca de repetidos")
    scan.add_argument(
        "--duplicate-max-size-mb",
        type=int,
        default=512,
        help="no modo rapido, nao calcula hash de arquivos maiores que este valor",
    )
    scan.add_argument(
        "--full-duplicates",
        action="store_true",
        help="busca repetidos sem limite de tempo/tamanho, incluindo arquivos grandes",
    )
    scan.add_argument("--json", dest="json_path", help="salva a pre-visualizacao em JSON")
    scan.add_argument("--csv", dest="csv_path", help="salva o plano de movimentacao em CSV")
    add_log_args(scan)
    add_performance_args(scan)

    apply = subparsers.add_parser("apply", help="aplica um plano gerado pelo scan")
    apply.add_argument("path", nargs="?", default=str(default_documents_path()))
    apply.add_argument("--plan", required=True, help="arquivo JSON criado pelo comando scan")
    apply.add_argument("--yes", action="store_true", help="confirma a movimentacao real")
    add_log_args(apply)

    dedupe = subparsers.add_parser("dedupe", help="move repetidos para _duplicados")
    dedupe.add_argument("path", nargs="?", default=str(default_documents_path()))
    dedupe.add_argument("--yes", action="store_true", help="confirma a movimentacao real")
    dedupe.add_argument("--duplicate-time-limit", type=float, default=90.0, help="segundos para busca de repetidos")
    dedupe.add_argument(
        "--duplicate-max-size-mb",
        type=int,
        default=512,
        help="no modo rapido, nao calcula hash de arquivos maiores que este valor",
    )
    dedupe.add_argument(
        "--full-duplicates",
        action="store_true",
        help="busca repetidos sem limite de tempo/tamanho, incluindo arquivos grandes",
    )
    dedupe.add_argument("--all-exact", action="store_true", help="tambem move exatos sem marcador claro de copia")
    dedupe.add_argument(
        "--include-cad",
        action="store_true",
        help="inclui arquivos CAD de Documentos na busca/movimentacao de duplicatas",
    )
    add_log_args(dedupe)
    add_performance_args(dedupe)

    subparsers.add_parser("gui", help="abre a interface grafica")
    return parser


def make_logger(args: argparse.Namespace, root: str | Path, operation: str) -> tuple[logging.Logger | None, Path | None]:
    if args.no_log_file:
        return None, None
    logger, log_path = create_operation_logger(root, mode="documents", operation=operation, console=args.verbose)
    logger.info("comando=%s", operation)
    logger.info("raiz=%s", root)
    return logger, log_path


def resolve_workers(args: argparse.Namespace) -> tuple[int, str]:
    mode = normalize_performance_mode(getattr(args, "performance", "balanced"))
    profile = detect_hardware()
    workers = getattr(args, "workers", None) or profile.workers_for(mode)
    return max(1, workers), profile.summary(mode)


def log_scan(logger: logging.Logger | None, scan: ScanResult) -> None:
    if logger is None:
        return
    logger.info("gerado_em=%s", scan.generated_at)
    for key, value in scan.stats.items():
        logger.info("stat.%s=%s", key, value)
    for index, item in enumerate(scan.plan, start=1):
        logger.info(
            "plano[%04d] action=%s category=%s source=%s destination=%s reason=%s is_directory=%s size=%s",
            index,
            item.action,
            item.category,
            item.source,
            item.destination,
            item.reason,
            item.is_directory,
            item.size,
        )
    for index, group in enumerate(scan.duplicates, start=1):
        logger.info(
            "duplicata[%04d] kind=%s size=%s sha256=%s reason=%s differences=%s files=%s",
            index,
            group.kind,
            group.size,
            group.sha256,
            group.reason,
            "; ".join(group.differences),
            " | ".join(group.files),
        )
    for item in scan.skipped:
        logger.warning("%s", item)
    for item in scan.errors:
        logger.error("%s", item)


def log_apply(logger: logging.Logger | None, result: ApplyResult) -> None:
    if logger is None:
        return
    logger.info("movimentos=%s ignorados=%s erros=%s", len(result.moved), len(result.skipped), len(result.errors))
    for source, destination in result.moved:
        logger.info("move source=%s destination=%s", source, destination)
    for item in result.skipped:
        logger.warning("%s", item)
    for item in result.errors:
        logger.error("%s", item)


def print_scan_details(scan: ScanResult) -> None:
    for item in scan.plan:
        print(f"Plano: {item.action} | {item.source} -> {item.destination} | {item.reason}")
    for group in scan.duplicates:
        print(f"Duplicata {group.kind}: {len(group.files)} arquivos | {group.reason}")
        for file_path in group.files:
            print(f"  - {file_path}")
    for item in scan.skipped:
        print(f"Aviso: {item}")
    for item in scan.errors:
        print(f"Erro: {item}", file=sys.stderr)


def command_scan(args: argparse.Namespace) -> int:
    duplicate_time_limit = None if args.full_duplicates else args.duplicate_time_limit
    duplicate_max_size_mb = None if args.full_duplicates else args.duplicate_max_size_mb
    workers, hardware_summary = resolve_workers(args)
    logger, log_path = make_logger(args, args.path, "scan")
    if logger:
        logger.info(
            "opcoes compat_names=%s include_duplicates=%s include_cad=%s full_duplicates=%s duplicate_time_limit=%s duplicate_max_size_mb=%s",
            args.compat_names,
            not args.no_duplicates,
            args.include_cad,
            args.full_duplicates,
            duplicate_time_limit,
            duplicate_max_size_mb,
        )
        logger.info("hardware=%s workers=%s", hardware_summary, workers)
    scan = scan_directory(
        args.path,
        compat_names=args.compat_names,
        include_duplicates=not args.no_duplicates,
        include_cad=args.include_cad,
        duplicate_time_limit=duplicate_time_limit,
        duplicate_max_size_mb=duplicate_max_size_mb,
        hash_workers=workers,
    )
    log_scan(logger, scan)
    stats = scan.stats
    print(f"Raiz: {scan.root}")
    print(f"Movimentos sugeridos: {stats['planned_moves']}")
    print(f"Duplicados exatos: {stats['exact_duplicate_groups']} grupos")
    print(f"Copias exatas para lote: {stats['batch_safe_duplicate_groups']} grupos")
    print(f"Possiveis duplicados: {stats['possible_duplicate_groups']} grupos")
    print(f"Arquivos exatos extras: {stats['duplicate_files']}")
    print(f"Ignorados: {stats['skipped']}")
    print(f"Erros: {stats['errors']}")
    print(f"Hardware: {hardware_summary}")
    if args.verbose:
        print_scan_details(scan)

    if args.json_path:
        target = write_scan_json(scan, args.json_path)
        print(f"JSON salvo em: {target}")
    if args.csv_path:
        target = write_plan_csv(scan, args.csv_path)
        print(f"CSV salvo em: {target}")
    if log_path:
        print(f"Log completo: {log_path}")
    if logger:
        close_logger(logger)
    return 1 if scan.errors else 0


def command_apply(args: argparse.Namespace) -> int:
    logger, log_path = make_logger(args, args.path, "apply")
    if logger:
        logger.info("plan=%s yes=%s dry_run=%s", args.plan, args.yes, not args.yes)
    plan = load_plan_json(args.plan)
    result = apply_plan(plan, args.path, dry_run=not args.yes)
    log_apply(logger, result)
    mode = "PREVIA" if not args.yes else "APLICADO"
    print(f"{mode}: {len(result.moved)} movimentos")
    for source, destination in result.moved[:20]:
        print(f"- {source} -> {destination}")
    if len(result.moved) > 20:
        print(f"... mais {len(result.moved) - 20} movimentos")
    for item in result.skipped:
        print(f"Ignorado: {item}")
    for item in result.errors:
        print(f"Erro: {item}", file=sys.stderr)
    if not args.yes:
        print("Use --yes para aplicar de verdade.")
    if log_path:
        print(f"Log completo: {log_path}")
    if logger:
        close_logger(logger)
    return 1 if result.errors else 0


def command_dedupe(args: argparse.Namespace) -> int:
    duplicate_time_limit = None if args.full_duplicates else args.duplicate_time_limit
    duplicate_max_size_mb = None if args.full_duplicates else args.duplicate_max_size_mb
    workers, hardware_summary = resolve_workers(args)
    logger, log_path = make_logger(args, args.path, "dedupe")
    if logger:
        logger.info(
            "opcoes yes=%s dry_run=%s full_duplicates=%s duplicate_time_limit=%s duplicate_max_size_mb=%s all_exact=%s include_cad=%s",
            args.yes,
            not args.yes,
            args.full_duplicates,
            duplicate_time_limit,
            duplicate_max_size_mb,
            args.all_exact,
            args.include_cad,
        )
        logger.info("hardware=%s workers=%s", hardware_summary, workers)
    result = move_duplicates_to_quarantine(
        args.path,
        dry_run=not args.yes,
        duplicate_time_limit=duplicate_time_limit,
        duplicate_max_size_mb=duplicate_max_size_mb,
        hash_workers=workers,
        include_manual_exact=args.all_exact,
        include_cad=args.include_cad,
    )
    log_apply(logger, result)
    mode = "PREVIA" if not args.yes else "APLICADO"
    print(f"{mode}: {len(result.moved)} repetidos exatos movidos para _duplicados")
    print(f"Hardware: {hardware_summary}")
    for source, destination in result.moved[:20]:
        print(f"- {source} -> {destination}")
    if len(result.moved) > 20:
        print(f"... mais {len(result.moved) - 20} movimentos")
    for item in result.errors:
        print(f"Erro: {item}", file=sys.stderr)
    for item in result.skipped[:20]:
        print(f"Mantido: {item}")
    if not args.yes:
        print("Use --yes para aplicar de verdade.")
    if log_path:
        print(f"Log completo: {log_path}")
    if logger:
        close_logger(logger)
    return 1 if result.errors else 0


def command_gui() -> int:
    from arruma_dir.gui import run

    run()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command in (None, "gui"):
        return command_gui()
    if args.command == "scan":
        return command_scan(args)
    if args.command == "apply":
        return command_apply(args)
    if args.command == "dedupe":
        return command_dedupe(args)

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
