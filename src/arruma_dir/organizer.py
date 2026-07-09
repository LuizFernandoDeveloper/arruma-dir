from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import threading
import time
import unicodedata
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


CHUNK_SIZE = 1024 * 1024
INVALID_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
LEADING_NUMBER_RE = re.compile(r"^\s*\d+\s*[-_. ]+\s*")
SPACES_RE = re.compile(r"\s+")
NON_WORD_RE = re.compile(r"[^a-z0-9]+")
RESERVED_WINDOWS_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

SKIP_NAMES = {
    "desktop.ini",
    "thumbs.db",
    ".ds_store",
    "$recycle.bin",
    "system volume information",
}

GENERATED_DIRS = {"_arruma_dir", "_duplicados"}
PRODUCTIVITY_DIRS = {"entrada", "projetos", "areas", "recursos", "arquivo"}
PROTECTED_APP_DIR_NAMES = {
    "acade 2026",
    "anaconda projects",
    "battlefield 4",
    "blocos de anotacoes do onenote",
    "catia composer",
    "catiacomposer",
    "custom office templates",
    "factory io",
    "fluidsim hydraulics",
    "gravacoes de som",
    "matlab",
    "minhas formas",
    "modelos personalizados do office",
    "onenote notebooks",
    "solidworks downloads",
    "solidworks visualize content",
    "solidworkscomposer",
    "sound recordings",
    "sw log files",
    "visual studio 18",
    "visual studio 2022",
}
SKIP_WALK_DIRS = GENERATED_DIRS | {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build",
    "target",
}


@dataclass(frozen=True)
class Topic:
    id: str
    label: str
    directory: str
    keywords: tuple[str, ...] = ()
    extensions: tuple[str, ...] = ()


DEFAULT_TOPICS: tuple[Topic, ...] = (
    Topic(
        "automacao",
        "Projetos de automacao e codigo",
        "projetos/automacao_codigo",
        (
            "automacao",
            "automation",
            "codigo",
            "code",
            "script",
            "python",
            "powershell",
            "windows powershell",
            "wsl",
            "visual studio",
            "vscode",
            "uml",
            "anaconda",
            "rust",
            "web",
            "app",
            "plc",
            "open plc",
        ),
        (
            ".py",
            ".ps1",
            ".bat",
            ".cmd",
            ".sh",
            ".js",
            ".ts",
            ".tsx",
            ".jsx",
            ".json",
            ".yaml",
            ".yml",
            ".toml",
            ".rs",
            ".html",
            ".css",
            ".sql",
        ),
    ),
    Topic(
        "escrita",
        "Projetos de escrita",
        "projetos/escrita",
        (
            "projetos literarios",
            "projeto literario",
            "literario",
            "literarios",
            "livro autoral",
            "roteiro",
            "escrita",
        ),
    ),
    Topic(
        "engenharia",
        "Projetos de engenharia",
        "projetos/engenharia",
        (
            "fotos de projetos",
            "portfolio programacao de cnc",
            "portifolio programacao de cnc",
            "lancamento de produto",
            "chocadeira",
            "forno",
            "corning",
            "cnc",
        ),
    ),
    Topic(
        "engenharia_referencia",
        "Recursos de engenharia",
        "recursos/engenharia",
        (
            "engenharia",
            "solidworks",
            "solid works",
            "catia",
            "composer",
            "factory io",
            "fluidsim",
            "matlab",
            "industrializacao",
            "barramento",
            "projeto eletrico",
            "tew",
            "raven",
        ),
        (
            ".dwg",
            ".dxf",
            ".step",
            ".stp",
            ".sldprt",
            ".sldasm",
            ".slddrw",
            ".tewzip",
            ".m",
            ".slx",
        ),
    ),
    Topic(
        "estudos",
        "Recursos de estudo",
        "recursos/estudos",
        (
            "estudo",
            "estudos",
            "pesquisa",
            "cientifica",
            "cientificas",
            "senai",
            "atividade",
            "aula",
            "curso",
            "faculdade",
            "trabalho escolar",
        ),
    ),
    Topic(
        "saude",
        "Area saude",
        "areas/saude",
        (
            "academia",
            "saude",
            "treino",
            "anamnese",
            "next fit",
            "corporal",
            "classificacao corporal",
        ),
    ),
    Topic(
        "carreira",
        "Area carreira",
        "areas/carreira",
        (
            "curriculo",
            "curriculum",
            "cv",
            "portfolio",
            "portifolio",
            "linkedin",
            "vaga",
            "emprego",
            "profissional",
        ),
    ),
    Topic(
        "empresas",
        "Area empresas e financeiro",
        "areas/empresas_financeiro",
        (
            "empresa",
            "empresas",
            "cnpj",
            "nota fiscal",
            "contrato",
            "extrato",
            "financeiro",
            "banco",
            "pagamento",
        ),
    ),
    Topic(
        "midia",
        "Recursos de midia",
        "recursos/midia",
        (
            "foto",
            "fotos",
            "imagem",
            "captura",
            "print",
            "screenshot",
            "gravacao",
            "gravacoes",
            "sound",
            "recording",
            "meme",
        ),
        (
            ".jpg",
            ".jpeg",
            ".png",
            ".gif",
            ".webp",
            ".bmp",
            ".svg",
            ".mp3",
            ".wav",
            ".m4a",
            ".mp4",
            ".mov",
            ".avi",
            ".mkv",
        ),
    ),
    Topic(
        "modelos",
        "Recursos de modelos e Office",
        "recursos/modelos_office",
        (
            "template",
            "templates",
            "modelo",
            "modelos",
            "office",
            "onenote",
            "notebook",
            "minhas formas",
            "formas",
        ),
        (".dotx", ".potx", ".xltx", ".one"),
    ),
    Topic(
        "leitura",
        "Recursos de leitura",
        "recursos/leitura",
        (
            "para ler",
            "leitura",
            "livro",
            "livros",
            "ebook",
            "artigo",
        ),
    ),
    Topic(
        "pessoal",
        "Area pessoal",
        "areas/pessoal",
        (
            "luiz fernando",
            "pessoal",
            "documento pessoal",
            "exame",
            "exames",
            "comprovante",
            "rotina",
        ),
    ),
    Topic(
        "documentos_referencia",
        "Recursos de documentos",
        "recursos/documentos",
        (),
        (
            ".doc",
            ".docx",
            ".pdf",
            ".txt",
            ".rtf",
            ".odt",
            ".xls",
            ".xlsx",
            ".csv",
            ".ppt",
            ".pptx",
            ".url",
        ),
    ),
    Topic("entrada", "Entrada para revisar", "entrada/revisar", ()),
)


TOPIC_DIRS = {Path(topic.directory).parts[0].lower() for topic in DEFAULT_TOPICS} | PRODUCTIVITY_DIRS


@dataclass
class PlanItem:
    action: str
    source: str
    destination: str
    category: str
    reason: str
    is_directory: bool
    size: int | None = None

    @classmethod
    def from_dict(cls, payload: dict) -> "PlanItem":
        return cls(**payload)


@dataclass
class DuplicateGroup:
    sha256: str
    size: int
    files: list[str]
    kind: str = "exact"
    reason: str = "mesmo tamanho e mesmo SHA-256"
    differences: list[str] = field(default_factory=list)


@dataclass
class ScanResult:
    root: str
    generated_at: str
    plan: list[PlanItem] = field(default_factory=list)
    duplicates: list[DuplicateGroup] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    file_summary: dict[str, int] = field(default_factory=dict)
    directory_summary: dict[str, int] = field(default_factory=dict)

    @property
    def stats(self) -> dict[str, int]:
        exact_groups = [group for group in self.duplicates if group.kind == "exact"]
        possible_groups = [group for group in self.duplicates if group.kind == "possible"]
        batch_groups = [group for group in exact_groups if is_batch_safe_duplicate_group(group)]
        return {
            "planned_moves": len(self.plan),
            "duplicate_groups": len(self.duplicates),
            "exact_duplicate_groups": len(exact_groups),
            "batch_safe_duplicate_groups": len(batch_groups),
            "possible_duplicate_groups": len(possible_groups),
            "duplicate_files": sum(max(0, len(group.files) - 1) for group in exact_groups),
            "skipped": len(self.skipped),
            "errors": len(self.errors),
        }

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["stats"] = self.stats
        return payload


@dataclass
class ApplyResult:
    moved: list[tuple[str, str]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def default_documents_path() -> Path:
    onedrive_docs = Path.home() / "OneDrive" / "Documentos"
    if onedrive_docs.exists():
        return onedrive_docs
    windows_docs = Path.home() / "Documents"
    if windows_docs.exists():
        return windows_docs
    return Path.home()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def remove_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def canonical_text(value: str) -> str:
    value = remove_accents(value).lower()
    value = re.sub(r"[_\-.]+", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return SPACES_RE.sub(" ", value).strip()


def strip_leading_number(value: str) -> str:
    cleaned = LEADING_NUMBER_RE.sub("", value).strip()
    return cleaned or value.strip()


def safe_display_name(value: str) -> str:
    value = INVALID_CHARS_RE.sub("-", value)
    value = SPACES_RE.sub(" ", value).strip(" .")
    return value or "sem_nome"


def slug_name(value: str) -> str:
    value = remove_accents(strip_leading_number(value)).lower()
    value = NON_WORD_RE.sub("_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "sem_nome"


def avoid_reserved_name(stem: str) -> str:
    if stem.upper() in RESERVED_WINDOWS_NAMES:
        return f"{stem}_"
    return stem


def clean_leaf_name(path: Path, compat_names: bool = False) -> str:
    original = strip_leading_number(path.name)
    suffix = path.suffix if path.is_file() else ""
    stem = original[: -len(suffix)] if suffix and original.lower().endswith(suffix.lower()) else original
    stem = strip_leading_number(stem)

    if compat_names:
        clean_stem = slug_name(stem)
        clean_suffix = suffix.lower()
    else:
        clean_stem = avoid_reserved_name(safe_display_name(stem))
        clean_suffix = suffix

    return f"{clean_stem}{clean_suffix}" if clean_suffix else clean_stem


def should_skip_name(name: str) -> bool:
    lowered = name.lower().strip()
    return (
        not lowered
        or lowered in SKIP_NAMES
        or lowered.startswith("~$")
        or lowered.startswith(".tmp")
    )


def is_protected_app_dir_name(name: str) -> bool:
    return canonical_text(strip_leading_number(name)) in PROTECTED_APP_DIR_NAMES


def is_generated_or_topic_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    lowered = path.name.lower()
    return lowered in GENERATED_DIRS or lowered in TOPIC_DIRS


def is_internal_generated_dir(path: Path) -> bool:
    return path.is_dir() and path.name.lower() in GENERATED_DIRS


def is_protected_app_dir(path: Path) -> bool:
    return path.is_dir() and is_protected_app_dir_name(path.name)


def looks_like_projects_cad_root(path: Path) -> bool:
    return (path / "organizar").is_dir() and (path / "projetos").is_dir()


def classify_entry(path: Path) -> tuple[Topic, str]:
    name = path.stem if path.is_file() else path.name
    text = canonical_text(strip_leading_number(name))
    extension = path.suffix.lower() if path.is_file() else ""

    best_topic: Topic | None = None
    best_score = 0
    best_keyword = ""
    for topic in DEFAULT_TOPICS:
        score = 0
        matched_keyword = ""
        for keyword in topic.keywords:
            normalized_keyword = canonical_text(keyword)
            if normalized_keyword and normalized_keyword in text:
                score += max(1, len(normalized_keyword.split()))
                if not matched_keyword:
                    matched_keyword = keyword
        if score > best_score:
            best_topic = topic
            best_score = score
            best_keyword = matched_keyword

    if best_topic is not None:
        return best_topic, f"palavra-chave: {best_keyword}"

    if extension:
        for topic in DEFAULT_TOPICS:
            if extension in topic.extensions:
                return topic, f"extensao: {extension}"

    return DEFAULT_TOPICS[-1], "sem regra forte"


def cleaned_name_matches_topic(path: Path, topic: Topic, compat_names: bool = False) -> bool:
    clean = clean_leaf_name(path, compat_names=compat_names)
    clean_text = canonical_text(clean)
    return clean_text in {
        canonical_text(topic.directory),
        canonical_text(Path(topic.directory).name),
        canonical_text(topic.label),
        canonical_text(topic.id),
    }


def ensure_inside(root: Path, target: Path) -> None:
    root_resolved = root.resolve()
    target_resolved = target.resolve(strict=False)
    try:
        target_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"Destino fora da raiz: {target}") from exc


def unique_path(target: Path) -> Path:
    if not target.exists():
        return target

    suffix = target.suffix
    stem = target.name[: -len(suffix)] if suffix else target.name
    parent = target.parent
    counter = 2
    while True:
        candidate = parent / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def summarize_file(path: Path, root: Path, file_summary: dict[str, int], directory_summary: dict[str, int]) -> None:
    ext = path.suffix.lower() or "(sem extensão)"
    file_summary[ext] = file_summary.get(ext, 0) + 1
    try:
        relative = path.relative_to(root)
    except ValueError:
        directory = "(fora da raiz)"
    else:
        directory = relative.parts[0] if len(relative.parts) > 1 else "(raiz)"
    directory_summary[directory] = directory_summary.get(directory, 0) + 1


def scan_directory(
    root: str | Path,
    *,
    compat_names: bool = False,
    include_duplicates: bool = True,
    duplicate_time_limit: float | None = 90.0,
    duplicate_max_size_mb: int | None = 512,
    hash_workers: int = 1,
    cancel_event: threading.Event | None = None,
) -> ScanResult:
    root_path = Path(root).expanduser()
    if not root_path.exists():
        raise FileNotFoundError(root_path)
    if not root_path.is_dir():
        raise NotADirectoryError(root_path)

    result = ScanResult(root=str(root_path), generated_at=utc_now())

    if is_cancelled(cancel_event):
        result.skipped.append("operacao cancelada pelo usuario antes da listagem")
        return result

    if looks_like_projects_cad_root(root_path):
        result.errors.append(
            "raiz parece um ambiente de Projetos/CAD com pastas 'organizar' e 'projetos'; "
            "use o modo Projetos/CAD ou o comando arruma-projetos"
        )
        return result

    for entry in sorted(root_path.iterdir(), key=lambda item: item.name.lower()):
        if is_cancelled(cancel_event):
            result.skipped.append("operacao cancelada pelo usuario durante a previa")
            break
        if should_skip_name(entry.name):
            result.skipped.append(str(entry))
            continue
        if is_internal_generated_dir(entry):
            continue
        if is_generated_or_topic_dir(entry):
            result.skipped.append(str(entry))
            continue
        if is_protected_app_dir(entry):
            result.skipped.append(f"pasta gerenciada por programa: {entry}")
            continue

        try:
            topic, reason = classify_entry(entry)
            target_dir = root_path / topic.directory
            is_dir = entry.is_dir()
            if is_dir and cleaned_name_matches_topic(entry, topic, compat_names=compat_names):
                action = "merge_dir"
                destination = target_dir
            else:
                action = "move"
                destination = target_dir / clean_leaf_name(entry, compat_names=compat_names)

            if entry.resolve(strict=False) == destination.resolve(strict=False):
                result.skipped.append(str(entry))
                continue

            ensure_inside(root_path, destination)
            size = entry.stat().st_size if entry.is_file() else None
            result.plan.append(
                PlanItem(
                    action=action,
                    source=str(entry),
                    destination=str(destination),
                    category=topic.directory,
                    reason=reason,
                    is_directory=is_dir,
                    size=size,
                )
            )
        except OSError as exc:
            result.errors.append(f"{entry}: {exc}")

    if include_duplicates:
        duplicate_result = find_duplicate_files(
            root_path,
            time_limit_seconds=duplicate_time_limit,
            max_file_size_mb=duplicate_max_size_mb,
            workers=hash_workers,
            cancel_event=cancel_event,
        )
        result.duplicates = duplicate_result.duplicates
        result.skipped.extend(duplicate_result.skipped)
        result.errors.extend(duplicate_result.errors)
        result.file_summary = duplicate_result.file_summary
        result.directory_summary = duplicate_result.directory_summary
    else:
        if is_cancelled(cancel_event):
            result.skipped.append("operacao cancelada pelo usuario antes do resumo de arquivos")
        else:
            for path in iter_files(root_path):
                if is_cancelled(cancel_event):
                    result.skipped.append("operacao cancelada durante o resumo de arquivos")
                    break
                summarize_file(path, root_path, result.file_summary, result.directory_summary)

    return result


def write_scan_json(scan: ScanResult, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(scan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def write_plan_csv(scan: ScanResult, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["action", "category", "source", "destination", "reason", "is_directory"])
        for item in scan.plan:
            writer.writerow(
                [item.action, item.category, item.source, item.destination, item.reason, item.is_directory]
            )
    return target


def load_plan_json(path: str | Path) -> list[PlanItem]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [PlanItem.from_dict(item) for item in payload.get("plan", [])]


def apply_plan(
    plan: Iterable[PlanItem],
    root: str | Path,
    *,
    dry_run: bool = False,
    cancel_event: threading.Event | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> ApplyResult:
    root_path = Path(root).expanduser()
    result = ApplyResult()
    plan_list = list(plan)
    total_items = len(plan_list)

    for i, item in enumerate(plan_list):
        if progress_callback:
            progress_callback(i + 1, total_items)
        if is_cancelled(cancel_event):
            raise InterruptedError("Aplicacao do plano cancelada pelo usuario.")
        source = Path(item.source)
        destination = Path(item.destination)
        try:
            ensure_inside(root_path, source)
            ensure_inside(root_path, destination)
            if not source.exists():
                result.skipped.append(f"nao existe: {source}")
                continue

            if item.action == "merge_dir":
                if not source.is_dir():
                    result.skipped.append(f"nao e pasta: {source}")
                    continue
                moves = _merge_directory(source, destination, dry_run=dry_run, cancel_event=cancel_event)
                result.moved.extend(moves)
            elif item.action == "move":
                target = unique_path(destination)
                if dry_run:
                    result.moved.append((str(source), str(target)))
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(target))
                result.moved.append((str(source), str(target)))
            else:
                result.skipped.append(f"acao desconhecida: {item.action} em {source}")
        except Exception as exc:  # noqa: BLE001 - CLI/GUI report all filesystem failures.
            result.errors.append(f"{item.source}: {exc}")

    return result


def rollback_moves(
    moves: Iterable[tuple[str, str]],
    root: str | Path,
    *,
    dry_run: bool = False,
    cancel_event: threading.Event | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> ApplyResult:
    root_path = Path(root).expanduser()
    result = ApplyResult()
    moves_list = list(moves)
    total_items = len(moves_list)

    for index, (original_path, current_path) in enumerate(reversed(moves_list), start=1):
        if progress_callback:
            progress_callback(index, total_items)
        if is_cancelled(cancel_event):
            raise InterruptedError("Reversao cancelada pelo usuario.")

        original = Path(original_path)
        current = Path(current_path)
        try:
            ensure_inside(root_path, original)
            ensure_inside(root_path, current)
            if not current.exists():
                result.skipped.append(f"nao existe para voltar: {current}")
                continue
            if original.exists():
                result.errors.append(f"destino original ocupado: {original}")
                continue
            if dry_run:
                result.moved.append((str(current), str(original)))
                continue
            original.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(current), str(original))
            result.moved.append((str(current), str(original)))
        except Exception as exc:  # noqa: BLE001 - CLI/GUI report all filesystem failures.
            result.errors.append(f"{current}: {exc}")

    return result


def _merge_directory(
    source: Path, destination: Path, *, dry_run: bool = False, cancel_event: threading.Event | None = None
) -> list[tuple[str, str]]:
    moves: list[tuple[str, str]] = []
    if not dry_run:
        destination.mkdir(parents=True, exist_ok=True)

    for child in sorted(source.iterdir(), key=lambda item: item.name.lower()):
        if is_cancelled(cancel_event):
            raise InterruptedError("Aplicacao do plano cancelada pelo usuario.")
        if should_skip_name(child.name):
            continue
        target = unique_path(destination / child.name)
        if dry_run:
            moves.append((str(child), str(target)))
            continue
        shutil.move(str(child), str(target))
        moves.append((str(child), str(target)))

    if not dry_run:
        try:
            source.rmdir()
        except OSError:
            pass
    return moves


def iter_files(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        dirnames[:] = [
            dirname
            for dirname in dirnames
            if not should_skip_name(dirname)
            and not dirname.startswith(".")
            and not is_protected_app_dir_name(dirname)
            and dirname.lower() not in SKIP_WALK_DIRS
        ]
        for filename in filenames:
            if should_skip_name(filename):
                continue
            path = current / filename
            if path.is_file():
                yield path


def is_cancelled(cancel_event: threading.Event | None) -> bool:
    return bool(cancel_event and cancel_event.is_set())


def file_sha256(path: Path, *, cancel_event: threading.Event | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while True:
            if is_cancelled(cancel_event):
                raise InterruptedError("operacao cancelada pelo usuario")
            chunk = file.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def hash_candidates_parallel(
    candidates: list[Path],
    *,
    workers: int,
    cancel_event: threading.Event | None,
) -> tuple[dict[str, list[str]], dict[str, str], list[str], bool]:
    by_hash: dict[str, list[str]] = {}
    hash_by_path: dict[str, str] = {}
    errors: list[str] = []
    cancelled = False
    max_workers = max(1, min(workers, len(candidates)))

    if max_workers == 1:
        for path in candidates:
            if is_cancelled(cancel_event):
                cancelled = True
                break
            try:
                digest = file_sha256(path, cancel_event=cancel_event)
            except InterruptedError:
                cancelled = True
                break
            except OSError as exc:
                errors.append(f"{path}: {exc}")
                continue
            hash_by_path[str(path)] = digest
            by_hash.setdefault(digest, []).append(str(path))
        return by_hash, hash_by_path, errors, cancelled

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="arruma-hash") as executor:
        pending: set[Future[tuple[Path, str]]] = {
            executor.submit(lambda item: (item, file_sha256(item, cancel_event=cancel_event)), path)
            for path in candidates
        }
        while pending:
            if is_cancelled(cancel_event):
                cancelled = True
                for future in pending:
                    future.cancel()
                break
            done, pending = wait(pending, timeout=0.2, return_when=FIRST_COMPLETED)
            for future in done:
                try:
                    path, digest = future.result()
                except InterruptedError:
                    cancelled = True
                    continue
                except OSError as exc:
                    errors.append(str(exc))
                    continue
                hash_by_path[str(path)] = digest
                by_hash.setdefault(digest, []).append(str(path))
    return by_hash, hash_by_path, errors, cancelled


def find_duplicate_files(
    root: str | Path,
    *,
    max_files: int | None = None,
    max_file_size_mb: int | None = None,
    time_limit_seconds: float | None = None,
    workers: int = 1,
    cancel_event: threading.Event | None = None,
) -> ScanResult:
    root_path = Path(root).expanduser()
    result = ScanResult(root=str(root_path), generated_at=utc_now())
    started_at = time.monotonic()
    max_bytes = max_file_size_mb * 1024 * 1024 if max_file_size_mb else None
    file_paths: list[Path] = []
    by_size: dict[int, list[Path]] = {}
    hash_by_path: dict[str, str] = {}
    skipped_large = 0

    def expired() -> bool:
        return time_limit_seconds is not None and (time.monotonic() - started_at) >= time_limit_seconds

    for index, path in enumerate(iter_files(root_path), start=1):
        if is_cancelled(cancel_event):
            result.skipped.append("duplicatas: operacao cancelada pelo usuario durante a listagem")
            break
        if expired():
            result.skipped.append(
                f"duplicatas: limite de tempo atingido na listagem/hash rapido: {time_limit_seconds}s; "
                "use --full-duplicates para varredura completa"
            )
            break
        if max_files is not None and index > max_files:
            result.skipped.append(f"limite de arquivos atingido na busca de repetidos: {max_files}")
            break
        file_paths.append(path)
        summarize_file(path, root_path, result.file_summary, result.directory_summary)
        try:
            size = path.stat().st_size
        except OSError as exc:
            result.errors.append(f"{path}: {exc}")
            continue
        if max_bytes is not None and size > max_bytes:
            skipped_large += 1
            continue
        if size <= 0:
            continue
        by_size.setdefault(size, []).append(path)

    if skipped_large:
        result.skipped.append(
            f"duplicatas: {skipped_large} arquivo(s) acima de {max_file_size_mb} MB nao foram hasheados "
            "no modo rapido; use --full-duplicates para incluir arquivos grandes"
        )

    for size, candidates in by_size.items():
        if is_cancelled(cancel_event):
            result.skipped.append("duplicatas: operacao cancelada pelo usuario durante hash")
            break
        if expired():
            result.skipped.append(
                f"duplicatas: limite de tempo atingido durante hash rapido: {time_limit_seconds}s; "
                "use --full-duplicates para varredura completa"
            )
            break
        if len(candidates) < 2:
            continue
        by_hash, hashed_paths, errors, cancelled = hash_candidates_parallel(
            candidates,
            workers=workers,
            cancel_event=cancel_event,
        )
        hash_by_path.update(hashed_paths)
        result.errors.extend(errors)
        if cancelled:
            result.skipped.append("duplicatas: operacao cancelada pelo usuario durante hash")
            break
        if expired():
            result.skipped.append(
                f"duplicatas: limite de tempo atingido durante hash rapido: {time_limit_seconds}s; "
                "use --full-duplicates para varredura completa"
            )
            break

        for digest, hashed_files in by_hash.items():
            if len(hashed_files) > 1:
                result.duplicates.append(
                    DuplicateGroup(
                        digest,
                        size,
                        sorted(hashed_files),
                        kind="exact",
                        reason="mesmo tamanho e mesmo SHA-256",
                    )
                )

    result.duplicates.extend(find_possible_duplicate_groups(root_path, file_paths, hash_by_path))
    return result


def duplicate_name_key(path: Path) -> str:
    stem = strip_leading_number(path.stem)
    stem = re.sub(r"\s*\((?:copia|copy|duplicado|duplicate|\d+)\)\s*$", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"\s*[-_ ]+(?:copia|copy|duplicado|duplicate)\b.*$", "", stem, flags=re.IGNORECASE)
    key = canonical_text(stem)
    return key if len(key) >= 3 else ""


def looks_like_copy_name(path: Path) -> bool:
    stem = strip_leading_number(path.stem)
    canonical = canonical_text(stem)
    return bool(
        re.search(r"\((?:copia|copy|duplicado|duplicate|\d+)\)\s*$", stem, flags=re.IGNORECASE)
        or re.search(r"[-_ ]+(?:copia|copy|duplicado|duplicate)\b", stem, flags=re.IGNORECASE)
        or canonical.startswith("copia de ")
        or " copia " in f" {canonical} "
        or " copy " in f" {canonical} "
        or " duplicado " in f" {canonical} "
    )


def is_batch_safe_duplicate_group(group: DuplicateGroup) -> bool:
    return group.kind == "exact" and any(looks_like_copy_name(Path(file_path)) for file_path in group.files)


def find_possible_duplicate_groups(
    root: Path,
    files: Iterable[Path],
    hash_by_path: dict[str, str],
) -> list[DuplicateGroup]:
    by_name: dict[str, list[Path]] = {}
    for path in files:
        key = duplicate_name_key(path)
        if key:
            by_name.setdefault(key, []).append(path)

    groups: list[DuplicateGroup] = []
    seen_signatures: set[tuple[str, ...]] = set()
    for candidates in by_name.values():
        if len(candidates) < 2:
            continue
        if not any(looks_like_copy_name(path) for path in candidates):
            continue
        file_names = sorted(str(path) for path in candidates)
        signature = tuple(file_names)
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)

        differences = analyze_file_differences(candidates, hash_by_path)
        if not differences:
            continue
        groups.append(
            DuplicateGroup(
                sha256="",
                size=0,
                files=file_names,
                kind="possible",
                reason="nomes iguais ou parecidos, mas ha diferencas",
                differences=differences,
            )
        )
    return groups


def analyze_file_differences(paths: Iterable[Path], hash_by_path: dict[str, str]) -> list[str]:
    paths = list(paths)
    differences: list[str] = []

    sizes: dict[int, int] = {}
    extensions: set[str] = set()
    hashes: set[str] = set()
    mtimes: set[int] = set()
    names: set[str] = set()

    for path in paths:
        names.add(path.name.lower())
        extensions.add(path.suffix.lower() or "(sem extensao)")
        digest = hash_by_path.get(str(path))
        if digest:
            hashes.add(digest)
        try:
            stat = path.stat()
        except OSError:
            continue
        sizes[stat.st_size] = sizes.get(stat.st_size, 0) + 1
        mtimes.add(int(stat.st_mtime))

    if len(sizes) == 1 and hashes and len(hashes) == 1:
        return []

    if len(sizes) > 1:
        ordered = sorted(sizes)
        differences.append(f"tamanhos diferentes: {ordered[0]} a {ordered[-1]} bytes")
    if len(extensions) > 1:
        differences.append("extensoes diferentes: " + ", ".join(sorted(extensions)))
    if len(hashes) > 1:
        differences.append("conteudo diferente: SHA-256 diferente")
    if len(mtimes) > 1:
        differences.append("datas de modificacao diferentes")
    if len(names) > 1:
        differences.append("nomes diferentes")

    return differences


def choose_duplicate_keeper(files: Iterable[str], root: str | Path) -> str:
    root_path = Path(root).expanduser()

    def score(file_path: str) -> tuple[int, int, int, str]:
        path = Path(file_path)
        text = canonical_text(path.name)
        copy_penalty = 1 if any(token in text for token in ("copia", "copy", "duplicado")) else 0
        try:
            relative = path.relative_to(root_path)
            depth = len(relative.parts)
        except ValueError:
            depth = 999
        try:
            mtime = int(path.stat().st_mtime)
        except OSError:
            mtime = 0
        return (copy_penalty, depth, -mtime, str(path).lower())

    return min(files, key=score)


def quarantine_name(root: Path, path: Path) -> Path:
    try:
        relative = path.relative_to(root)
        parts = relative.parts
    except ValueError:
        parts = (path.name,)
    safe_parts = [slug_name(part) for part in parts]
    return Path(*safe_parts)


def move_duplicates_to_quarantine(
    root: str | Path,
    duplicate_groups: Iterable[DuplicateGroup] | None = None,
    *,
    dry_run: bool = False,
    duplicate_time_limit: float | None = 90.0,
    duplicate_max_size_mb: int | None = 512,
    hash_workers: int = 1,
    cancel_event: threading.Event | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
    include_manual_exact: bool = False,
) -> ApplyResult:
    root_path = Path(root).expanduser()
    groups = (
        list(duplicate_groups)
        if duplicate_groups is not None
        else find_duplicate_files(
            root_path,
            time_limit_seconds=duplicate_time_limit,
            max_file_size_mb=duplicate_max_size_mb,
            workers=hash_workers,
            cancel_event=cancel_event,
        ).duplicates
    )
    quarantine = root_path / "_duplicados"
    result = ApplyResult()
    groups_list = list(groups)
    total_groups = len(groups_list)

    for i, group in enumerate(groups_list):
        if progress_callback:
            progress_callback(i + 1, total_groups)
        if is_cancelled(cancel_event):
            raise InterruptedError("Movimentacao de duplicatas cancelada pelo usuario.")
        if group.kind != "exact":
            result.skipped.append(f"mantido para decisao: {group.reason} ({len(group.files)} arquivos)")
            continue
        if not include_manual_exact and not is_batch_safe_duplicate_group(group):
            result.skipped.append(f"exato sem marcador de copia, mantido para decisao: {len(group.files)} arquivos")
            continue
        keeper = choose_duplicate_keeper(group.files, root_path)
        for file_path in group.files:
            if file_path == keeper:
                continue
            source = Path(file_path)
            try:
                if not source.exists():
                    result.skipped.append(f"nao existe: {source}")
                    continue
                target = quarantine / group.sha256[:12] / quarantine_name(root_path, source)
                ensure_inside(root_path, target)
                target = unique_path(target)
                if dry_run:
                    result.moved.append((str(source), str(target)))
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(target))
                result.moved.append((str(source), str(target)))
            except Exception as exc:  # noqa: BLE001 - GUI should show all failures.
                result.errors.append(f"{source}: {exc}")

    return result


def move_files_to_quarantine(
    root: str | Path,
    files: Iterable[str | Path],
    *,
    bucket: str = "manual",
    dry_run: bool = False,
    cancel_event: threading.Event | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> ApplyResult:
    root_path = Path(root).expanduser()
    quarantine = root_path / "_duplicados" / slug_name(bucket)
    result = ApplyResult()
    files_list = list(files)
    total_files = len(files_list)

    for i, file_path in enumerate(files_list):
        if progress_callback:
            progress_callback(i + 1, total_files)
        if is_cancelled(cancel_event):
            raise InterruptedError("Movimentacao de arquivo cancelada pelo usuario.")
        source = Path(file_path)
        try:
            ensure_inside(root_path, source)
            if not source.exists():
                result.skipped.append(f"nao existe: {source}")
                continue
            target = quarantine / quarantine_name(root_path, source)
            ensure_inside(root_path, target)
            target = unique_path(target)
            if dry_run:
                result.moved.append((str(source), str(target)))
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            result.moved.append((str(source), str(target)))
        except Exception as exc:  # noqa: BLE001 - GUI should show all failures.
            result.errors.append(f"{source}: {exc}")

    return result
