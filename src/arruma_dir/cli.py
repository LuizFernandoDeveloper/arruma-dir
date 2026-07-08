from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .organizer import (
    apply_plan,
    default_documents_path,
    load_plan_json,
    move_duplicates_to_quarantine,
    scan_directory,
    write_plan_csv,
    write_scan_json,
)


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
    scan.add_argument("--duplicate-time-limit", type=float, default=90.0, help="segundos para busca de repetidos")
    scan.add_argument("--duplicate-max-size-mb", type=int, default=512, help="ignora arquivos maiores que este valor")
    scan.add_argument("--full-duplicates", action="store_true", help="busca repetidos sem limite de tempo/tamanho")
    scan.add_argument("--json", dest="json_path", help="salva a pre-visualizacao em JSON")
    scan.add_argument("--csv", dest="csv_path", help="salva o plano de movimentacao em CSV")

    apply = subparsers.add_parser("apply", help="aplica um plano gerado pelo scan")
    apply.add_argument("path", nargs="?", default=str(default_documents_path()))
    apply.add_argument("--plan", required=True, help="arquivo JSON criado pelo comando scan")
    apply.add_argument("--yes", action="store_true", help="confirma a movimentacao real")

    dedupe = subparsers.add_parser("dedupe", help="move repetidos para _duplicados")
    dedupe.add_argument("path", nargs="?", default=str(default_documents_path()))
    dedupe.add_argument("--yes", action="store_true", help="confirma a movimentacao real")
    dedupe.add_argument("--duplicate-time-limit", type=float, default=90.0, help="segundos para busca de repetidos")
    dedupe.add_argument("--duplicate-max-size-mb", type=int, default=512, help="ignora arquivos maiores que este valor")
    dedupe.add_argument("--full-duplicates", action="store_true", help="busca repetidos sem limite de tempo/tamanho")
    dedupe.add_argument("--all-exact", action="store_true", help="tambem move exatos sem marcador claro de copia")

    subparsers.add_parser("gui", help="abre a interface grafica")
    return parser


def command_scan(args: argparse.Namespace) -> int:
    duplicate_time_limit = None if args.full_duplicates else args.duplicate_time_limit
    duplicate_max_size_mb = None if args.full_duplicates else args.duplicate_max_size_mb
    scan = scan_directory(
        args.path,
        compat_names=args.compat_names,
        include_duplicates=not args.no_duplicates,
        duplicate_time_limit=duplicate_time_limit,
        duplicate_max_size_mb=duplicate_max_size_mb,
    )
    stats = scan.stats
    print(f"Raiz: {scan.root}")
    print(f"Movimentos sugeridos: {stats['planned_moves']}")
    print(f"Duplicados exatos: {stats['exact_duplicate_groups']} grupos")
    print(f"Copias exatas para lote: {stats['batch_safe_duplicate_groups']} grupos")
    print(f"Possiveis duplicados: {stats['possible_duplicate_groups']} grupos")
    print(f"Arquivos exatos extras: {stats['duplicate_files']}")
    print(f"Ignorados: {stats['skipped']}")
    print(f"Erros: {stats['errors']}")

    if args.json_path:
        target = write_scan_json(scan, args.json_path)
        print(f"JSON salvo em: {target}")
    if args.csv_path:
        target = write_plan_csv(scan, args.csv_path)
        print(f"CSV salvo em: {target}")
    return 1 if scan.errors else 0


def command_apply(args: argparse.Namespace) -> int:
    plan = load_plan_json(args.plan)
    result = apply_plan(plan, args.path, dry_run=not args.yes)
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
    return 1 if result.errors else 0


def command_dedupe(args: argparse.Namespace) -> int:
    duplicate_time_limit = None if args.full_duplicates else args.duplicate_time_limit
    duplicate_max_size_mb = None if args.full_duplicates else args.duplicate_max_size_mb
    result = move_duplicates_to_quarantine(
        args.path,
        dry_run=not args.yes,
        duplicate_time_limit=duplicate_time_limit,
        duplicate_max_size_mb=duplicate_max_size_mb,
        include_manual_exact=args.all_exact,
    )
    mode = "PREVIA" if not args.yes else "APLICADO"
    print(f"{mode}: {len(result.moved)} repetidos exatos movidos para _duplicados")
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
    return 1 if result.errors else 0


def command_gui() -> int:
    from .gui import run

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
