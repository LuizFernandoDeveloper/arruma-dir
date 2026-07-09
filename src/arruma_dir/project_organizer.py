from __future__ import annotations

import csv
import ctypes
import hashlib
import json
import os
import re
import shutil
import threading
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterable, TypedDict

from arruma_dir.hardware import detect_hardware, normalize_performance_mode
from arruma_dir.logging_utils import close_logger, create_operation_logger


DEFAULT_ROOT = Path(r"F:\projetos")
STATE_DIR = "_arruma_projetos"
REPORTS_DIR = "reports"
DUPLICATES_DIR = "duplicados"
EXTERNAL_INBOX_DIR = "entrada_hds"
CHUNK_SIZE = 1024 * 1024

LEADING_NUMBER_RE = re.compile(r"^\s*\d+\s*[-_. ]+\s*")
PROJECT_CODE_RE = re.compile(r"\b[CPRS]\s*-?\s*\d{4,7}(?:[-_ ]?\d{1,4})?\b", re.IGNORECASE)
OPCAO_CODE_RE = re.compile(
    r"^(?:OP[- ]?\d{2,5}(?:[- ]?\d{1,4})*(?:[- ]?XXX)?|"
    r"\d{3,6}(?:[-_ ]\d{1,4})*(?:[-_ ]?REV\d{1,2})?)",
    re.IGNORECASE,
)

RAMTECH_STANDARD_DOCS = {
    "FX 05 - Fluxograma Industrializacao R02.pdf",
    "IT 05.01 - Criacao pasta virtual e montagem pasta fisica R01.pdf",
    "IT 05.02 - Padronizacao de Projetos R01.pdf",
    "IT 05.03 - Dimensionamento Barramento.pdf",
    "IT 05.04 - Documentacao para producao R01.pdf",
    "PO-05 - Politica de Industrializacao R01.pdf",
}

RAMTECH_PROJECT_SUBFOLDERS = (
    "1- Projeto Eletrico (Eplan)",
    "2- Projeto Eletrico (PDF)",
    "3- Projeto Eletrico (DWG)",
    "4- Projeto Mecanico",
    "5- Documentos Macrotec",
    "6- Referencias",
    "7- Fotos",
    "8- Documentos Inspecao",
    "9- Documentos Projetos",
    "10- Lista de Materiais Excel",
    "11- Lista de Plaquetas Excel",
    "12- Lista de Identificacoes Excel",
)

OPCAO_PROJECT_SUBFOLDERS = (
    "01 - Montagem",
    "02 - Pecas",
    "03 - Detalhamentos",
    "04 - Comerciais",
    "05 - CABOS",
    "06 - REFERENCIA",
    "07 - Renderings",
)

PROJECT_EXTENSIONS = {
    ".asmdot",
    ".bak",
    ".doc",
    ".docx",
    ".drwdot",
    ".dwg",
    ".dwt",
    ".dxf",
    ".edb",
    ".elk",
    ".epj",
    ".ept",
    ".fn1",
    ".iges",
    ".igs",
    ".msg",
    ".pdf",
    ".prtdot",
    ".ppe",
    ".proj",
    ".rar",
    ".slddrt",
    ".sldasm",
    ".slddrw",
    ".sldprt",
    ".step",
    ".stp",
    ".tewzip",
    ".xls",
    ".xlsx",
    ".xml",
    ".zip",
    ".zw1",
    ".zw9",
}

CAD_TREE_FILENAMES = {
    ".project",
}

CAD_TREE_EXTENSIONS = {
    ".ac$",
    ".asmdot",
    ".bak",
    ".ctb",
    ".drwdot",
    ".dwg",
    ".dwl",
    ".dwl2",
    ".dwt",
    ".dxf",
    ".edb",
    ".elk",
    ".epj",
    ".ept",
    ".lin",
    ".pat",
    ".pc3",
    ".proj",
    ".prtdot",
    ".sldasm",
    ".slddrt",
    ".slddrw",
    ".sldprt",
    ".stb",
    ".sv$",
    ".tewzip",
    ".zw1",
    ".zw9",
}

NOISE_EXTENSIONS = {".dwl", ".dwl2", ".err", ".log", ".tmp"}
NOISE_NAMES = {"desktop.ini", "thumbs.db"}
SKIP_DIR_NAMES = {
    STATE_DIR.lower(),
    ".git",
    ".svn",
    ".hg",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
}


@dataclass
class MoveOperation:
    action: str
    source: str
    destination: str
    reason: str


@dataclass
class DuplicateOperation:
    source: str
    destination: str
    keeper: str
    sha256: str
    size: int
    reason: str


@dataclass
class ExternalCandidate:
    source: str
    destination: str
    drive: str
    score: int
    reasons: list[str] = field(default_factory=list)
    size: int | None = None
    sha256: str | None = None
    duplicate_of: str | None = None
    decision: str = "copy_to_inbox"


class ProjectApplyResult(TypedDict):
    moved: list[str]
    copied: list[str]
    skipped: list[str]
    errors: list[str]
    moved_pairs: list[tuple[str, str]]
    copied_pairs: list[tuple[str, str]]


@dataclass
class ProjectReport:
    root: str
    generated_at: str
    organization: list[MoveOperation] = field(default_factory=list)
    duplicates: list[DuplicateOperation] = field(default_factory=list)
    external_candidates: list[ExternalCandidate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    file_summary: dict[str, int] = field(default_factory=dict)
    directory_summary: dict[str, int] = field(default_factory=dict)

    @property
    def stats(self) -> dict[str, int]:
        return {
            "organization_moves": len(self.organization),
            "duplicate_moves": len(self.duplicates),
            "external_candidates": len(self.external_candidates),
            "warnings": len(self.warnings),
            "errors": len(self.errors),
        }

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["stats"] = self.stats
        return payload


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def strip_accents(value: str) -> str:
    import unicodedata

    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def canonical_text(value: str) -> str:
    value = strip_accents(value).lower()
    value = LEADING_NUMBER_RE.sub("", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def slug(value: str) -> str:
    value = canonical_text(value)
    return re.sub(r"\s+", "_", value).strip("_") or "sem_nome"


def safe_filename(value: str) -> str:
    path = Path(value)
    suffix = path.suffix
    stem = path.name[: -len(suffix)] if suffix else path.name
    return f"{slug(stem)}{suffix}" if suffix else slug(path.name)


def is_noise_file(path: Path) -> bool:
    name = path.name.lower()
    return name in NOISE_NAMES or name.startswith("~$") or path.suffix.lower() in NOISE_EXTENSIONS


def is_cad_tree_file(path: Path) -> bool:
    name = path.name.lower()
    if name in CAD_TREE_FILENAMES:
        return True
    suffix = path.suffix.lower()
    if suffix in CAD_TREE_EXTENSIONS:
        return True
    return name.endswith(".proj.tewzip")


@lru_cache(maxsize=8192)
def directory_has_cad_marker(directory: str) -> bool:
    path = Path(directory)
    if (path / ".project").exists():
        return True
    try:
        entries = list(path.iterdir())
    except OSError:
        return False
    return any(entry.is_file() and is_cad_tree_file(entry) for entry in entries)


def is_inside_cad_project_tree(path: Path) -> bool:
    current = path.parent
    while current != current.parent:
        if directory_has_cad_marker(str(current)):
            return True
        current = current.parent
    return False


def is_cad_protected_file(path: Path) -> bool:
    return is_cad_tree_file(path) or is_inside_cad_project_tree(path)


def should_skip_dir(path: Path) -> bool:
    return path.name.lower() in SKIP_DIR_NAMES or path.name.startswith(".")


def state_path(root: Path, *parts: str) -> Path:
    return root / STATE_DIR / Path(*parts)


def ensure_inside(root: Path, target: Path) -> None:
    root_resolved = root.resolve()
    target_resolved = target.resolve(strict=False)
    try:
        target_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"Destino fora da raiz de projetos: {target}") from exc


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    suffix = path.suffix
    stem = path.name[: -len(suffix)] if suffix else path.name
    counter = 2
    while True:
        candidate = path.parent / f"{stem} ({counter}){suffix}"
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


def iter_files(root: Path, *, max_files: int | None = None) -> Iterable[Path]:
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        dirnames[:] = [name for name in dirnames if not should_skip_dir(current / name)]
        for filename in filenames:
            path = current / filename
            if is_noise_file(path):
                continue
            seen += 1
            if max_files is not None and seen > max_files:
                return
            yield path


def is_cancelled(cancel_event: threading.Event | None) -> bool:
    return bool(cancel_event and cancel_event.is_set())


def file_sha256(path: Path, *, cancel_event: threading.Event | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            if is_cancelled(cancel_event):
                raise InterruptedError("operacao cancelada pelo usuario")
            chunk = handle.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def hash_project_candidates(
    candidates: list[Path],
    *,
    workers: int,
    cancel_event: threading.Event | None,
) -> tuple[dict[str, list[Path]], list[str], bool]:
    by_hash: dict[str, list[Path]] = {}
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
            by_hash.setdefault(digest, []).append(path)
        return by_hash, errors, cancelled

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="arruma-projetos-hash") as executor:
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
                by_hash.setdefault(digest, []).append(path)
    return by_hash, errors, cancelled


def canonical_roots(root: Path) -> dict[str, Path]:
    base = root / "projetos"
    return {
        "root": root,
        "base": base,
        "ramtech": base / "Ramtech",
        "ramtech_projetos": base / "Ramtech" / "Projetos",
        "ramtech_modelos": base / "Ramtech" / "Modelos",
        "ramtech_padroes": base / "Ramtech" / "PADRAO RAMTECH",
        "ramtech_pastas": base / "Ramtech" / "PADRAO DE PASTAS",
        "ramtech_estudos": base / "Ramtech" / "Estudos referentes a macrotec",
        "ramtech_biblioteca": base / "Ramtech" / "Biblioteca Tecnica",
        "ramtech_fabricacao": base / "Ramtech" / "Fabricacao",
        "opcao": base / "Opcao",
        "opcao_mecanico": base / "Opcao" / "Projetos_Mecanicos",
        "opcao_catalogos": base / "Opcao" / "Catalogos",
        "opcao_cabos": base / "Opcao" / "Cabos",
        "opcao_componentes": base / "Opcao" / "Biblioteca_Componentes",
        "opcao_detalhamentos": base / "Opcao" / "Detalhamentos",
        "opcao_referencias": base / "Opcao" / "Referencias",
        "opcao_templates": base / "Opcao" / "Templates_SolidWorks",
        "meus": base / "Meus_Projetos",
        "referencias": base / "Referencias",
        "entrada": root / "organizar",
        "entrada_revisar": root / "entrada" / "revisar" / "organizar",
    }


def is_inside_any(path: Path, roots: Iterable[Path]) -> bool:
    resolved = path.resolve(strict=False)
    for root in roots:
        try:
            resolved.relative_to(root.resolve(strict=False))
            return True
        except ValueError:
            continue
    return False


def learned_model_summary() -> list[str]:
    return [
        "IT-05.01: projeto no padrao numero do projeto + PV + cliente.",
        "IT-05.01: subpastas 1 Eplan, 2 PDF, 3 DWG, 4 Mecanico, 5 Macrotec, 6 Referencias, 7 Fotos, 8 Inspecao, 9 Documentos Projetos.",
        "IT-05.02: padroes Macrotec/Ramtech com capa, folha interna, indice e folha de dados.",
        "IT-05.04: producao usa Identificacao de Projeto, Formulario de Inspecao, Desenho de Fabricacao e Caderno Eletromecanico.",
        "PO-05: manter sempre versao mais atualizada e evidenciar planejamento, analise, verificacao, analise critica e validacao.",
        "Opcao Industrial: separar projetos mecanicos numerados, biblioteca de componentes, catalogos OP, templates SolidWorks, cabos e referencias.",
        "Opcao Industrial: codigos OP e pastas numericas/REV indicam item mecanico ou projeto mecanico; arquivos SLDPRT/SLDASM/SLDDRW devem preservar relacao de montagem.",
        "CAD: mover somente arvores/pastas inteiras por padrao; arquivos individuais de SolidWorks, SolidWorks Electrical, EPLAN e AutoCAD ficam protegidos.",
        "SolidWorks Electrical/exportacao de estudo: .project e arquivos da pasta vizinha pertencem a uma arvore de projeto e nao sao desmontados.",
        "CAD: duplicatas de arquivos de projeto/modelo/desenho nao entram na quarentena automatica sem --include-cad-duplicates.",
    ]


def is_opcao_mechanical_context(path: Path, root: Path) -> bool:
    roots = canonical_roots(root)
    text = canonical_text(str(path))
    try:
        relative = path.relative_to(roots["entrada"])
        relative_text = canonical_text(str(relative))
    except ValueError:
        relative_text = text
    return (
        "4 projeto mecanico" in relative_text
        or "projeto mecanico" in relative_text
        or "opcao" in text
        or "opcao industrial" in text
        or "catalogo opcao" in text
    )


def classify_opcao(path: Path, root: Path) -> tuple[Path | None, str]:
    roots = canonical_roots(root)
    text = canonical_text(" ".join(path.parts))
    name_text = canonical_text(path.name)
    suffix = path.suffix.lower()

    if not is_opcao_mechanical_context(path, root):
        return None, "fora do contexto Opcao"

    if path.is_file() and is_cad_protected_file(path):
        return None, "arquivo CAD protegido para preservar referencias"

    if "solid 01 opcao industrial" in text or suffix in {".slddrt", ".prtdot", ".asmdot"}:
        return roots["opcao_templates"] / path.name, "Opcao: templates SolidWorks"

    if "catalogo opcao" in text or "03 catalogo" in text or "codigos op" in name_text:
        if "detalhamento" in text:
            return roots["opcao_detalhamentos"] / path.name, "Opcao: detalhamentos de catalogo"
        return roots["opcao_catalogos"] / path.name, "Opcao: catalogo"

    if "00000 componentes" in text or "componentes" in name_text:
        return roots["opcao_componentes"] / path.name, "Opcao: biblioteca de componentes"

    if "modelos de cabos" in text or " cabos " in f" {text} ":
        return roots["opcao_cabos"] / path.name, "Opcao: cabos"

    if "referencia" in text or "linha modelo" in text:
        return roots["opcao_referencias"] / path.name, "Opcao: referencias e linha modelo"

    if OPCAO_CODE_RE.search(path.name):
        if canonical_text(path.name).startswith("op"):
            return roots["opcao_componentes"] / "Itens_OP" / path.name, "Opcao: item OP de biblioteca"
        if path.is_dir():
            return roots["opcao_mecanico"] / path.name, "Opcao: projeto/item mecanico numerado"
        if suffix in {".sldprt", ".sldasm", ".slddrw", ".pdf", ".dwg", ".dxf"}:
            return roots["opcao_mecanico"] / "_pecas_soltas" / path.name, "Opcao: peca/desenho mecanico numerado"

    if suffix in {".sldprt", ".sldasm", ".slddrw"} and any(
        token in text for token in ("garra", "mordente", "pinca", "ventosa", "perfil", "cilindro", "suporte")
    ):
        return roots["opcao_componentes"] / "_pecas_soltas" / path.name, "Opcao: componente SolidWorks"

    return None, "sem regra Opcao segura"


def classify_for_root(path: Path, root: Path) -> tuple[Path | None, str]:
    roots = canonical_roots(root)
    text = canonical_text(" ".join(path.parts))
    name_text = canonical_text(path.name)
    suffix = path.suffix.lower()

    protected_roots = [
        roots["ramtech"],
        roots["meus"],
        roots["opcao"],
        roots["referencias"],
        state_path(root),
    ]
    if is_inside_any(path, protected_roots):
        return None, "ja esta em area canonica"

    if path.is_dir() and name_text in {"ramtech", "macrotec"}:
        return roots["ramtech"], "fundir pasta Ramtech/Macrotec na area canonica"

    if path.is_dir() and name_text in {"opcao", "opcao industrial"}:
        return roots["opcao"], "fundir pasta Opcao na area canonica"

    opcao_target, opcao_reason = classify_opcao(path, root)
    if opcao_target is not None:
        return opcao_target, opcao_reason

    if path == roots["entrada"] or is_inside_any(path, [roots["entrada"]]):
        if "opcao" in text or "opcao industrial" in text:
            if "cabo" in text:
                return roots["opcao_cabos"] / path.name, "material Opcao: cabos"
            if "catalogo" in text or "perfil" in text or "pinca" in text:
                return roots["opcao_catalogos"] / path.name, "material Opcao: catalogo/componente"
            return roots["opcao_mecanico"] / path.name, "material Opcao: projeto mecanico"
        if "ramtech" in text or "macrotec" in text:
            return roots["ramtech"] / "_entrada_revisar" / path.name, "material Ramtech/Macrotec fora do lugar"

    if suffix == ".tewzip":
        if "forno" in text and "corning" in text:
            return roots["meus"] / "SolidWorks-Electrical" / "FORNO CORNING" / "Back" / path.name, "arquivo TEWZIP do Forno Corning"
        return roots["meus"] / "SolidWorks-Electrical" / "_arquivos_tewzip" / path.name, "arquivo TEWZIP"

    if suffix in {".pdf", ".xlsx", ".xls", ".doc", ".docx"}:
        standard_key = canonical_text(path.name)
        if any(canonical_text(doc) == standard_key for doc in RAMTECH_STANDARD_DOCS):
            return roots["ramtech_estudos"] / path.name, "documento normativo Ramtech/Macrotec"
        if any(term in text for term in ("protec", "simulation instructor", "maquinas", "solidworks")):
            return roots["referencias"] / "Mecanica" / path.name, "referencia tecnica mecanica"

    if "padrao ramtech" in text:
        return roots["ramtech_padroes"] / path.name, "padrao Ramtech"

    if "padrao de pastas" in text:
        return roots["ramtech_pastas"] / path.name, "padrao de pastas Ramtech"

    if "biblioteca" in text and ("ramtech" in text or "macrotec" in text):
        return roots["ramtech_biblioteca"] / path.name, "biblioteca tecnica Ramtech/Macrotec"

    if "fabricacao" in text and ("ramtech" in text or "macrotec" in text):
        return roots["ramtech_fabricacao"] / path.name, "fabricacao Ramtech/Macrotec"

    if "modelo" in name_text and ("ramtech" in text or "macrotec" in text):
        return roots["ramtech_modelos"] / path.name, "modelo Ramtech/Macrotec"

    if PROJECT_CODE_RE.search(path.name):
        return roots["ramtech_projetos"] / path.name, "codigo de projeto Ramtech/Macrotec"

    if "ramtech" in text or "macrotec" in text:
        return roots["ramtech"] / "_entrada_revisar" / path.name, "material Ramtech/Macrotec para revisar"

    return None, "sem regra segura"


def project_scan_roots(root: Path, *, cancel_event: threading.Event | None = None) -> list[Path]:
    roots = canonical_roots(root)
    candidates = [root, roots["entrada"], roots["entrada_revisar"], roots["base"]]
    for staging_root in (roots["entrada"], roots["entrada_revisar"]):
        if not staging_root.exists():
            continue
        for child in sorted(staging_root.iterdir(), key=lambda item: item.name.lower()):
            if is_cancelled(cancel_event):
                return candidates
            if child.is_dir() and canonical_text(child.name) in {"4 projeto mecanico", "projeto mecanico"}:
                candidates.append(child)

    scan_roots: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        scan_roots.append(candidate)
    return scan_roots


def build_organization_plan(root: Path, *, cancel_event: threading.Event | None = None) -> list[MoveOperation]:
    operations: list[MoveOperation] = []
    roots = canonical_roots(root)
    scan_roots = project_scan_roots(root, cancel_event=cancel_event)

    for scan_root in scan_roots:
        if not scan_root.exists():
            continue
        for entry in sorted(scan_root.iterdir(), key=lambda item: item.name.lower()):
            if is_cancelled(cancel_event):
                return operations
            if entry.name.lower() in {"entrada", "organizar", "projetos", STATE_DIR.lower()}:
                continue
            if is_noise_file(entry):
                continue
            target, reason = classify_for_root(entry, root)
            if target is None:
                continue
            ensure_inside(root, target)
            action = "merge_dir" if entry.is_dir() and target.resolve(strict=False) in {
                roots["ramtech"].resolve(strict=False),
                roots["opcao"].resolve(strict=False),
            } else "move"
            operations.append(MoveOperation(action, str(entry), str(target), reason))
    return operations


def path_priority(path: Path, root: Path) -> tuple[int, int, str]:
    roots = canonical_roots(root)
    text = canonical_text(str(path))
    copy_penalty = 1 if any(token in text for token in ("copia", "copy", "old", "backup")) else 0
    if is_inside_any(path, [roots["ramtech_estudos"], roots["ramtech_projetos"], roots["ramtech_modelos"], roots["opcao"], roots["meus"]]):
        area_score = 0
    elif is_inside_any(path, [roots["entrada"]]):
        area_score = 2
    else:
        area_score = 1
    try:
        depth = len(path.relative_to(root).parts)
    except ValueError:
        depth = 999
    return (area_score + copy_penalty, depth, str(path).lower())


def duplicate_quarantine_target(root: Path, source: Path, digest: str) -> Path:
    try:
        rel = source.relative_to(root)
    except ValueError:
        rel = Path(source.drive.replace(":", "")) / source.relative_to(source.anchor)
    safe_parts = [slug(part) for part in rel.parts]
    return state_path(root, DUPLICATES_DIR, digest[:12], *safe_parts)


def find_duplicates(
    files_to_scan: list[Path],
    root: Path,
    *,
    max_size_mb: int | None,
    include_cad_duplicates: bool = False,
    hash_workers: int = 1,
    cancel_event: threading.Event | None = None,
) -> tuple[list[DuplicateOperation], int]:
    max_bytes = max_size_mb * 1024 * 1024 if max_size_mb else None
    by_size: dict[int, list[Path]] = {}
    skipped_cad = 0

    for path in files_to_scan:
        if is_cancelled(cancel_event):
            break
        if is_cad_protected_file(path) and not include_cad_duplicates:
            skipped_cad += 1
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size <= 0:
            continue
        if max_bytes is not None and size > max_bytes:
            continue
        by_size.setdefault(size, []).append(path)

    operations: list[DuplicateOperation] = []
    for size, candidates in by_size.items():
        if is_cancelled(cancel_event):
            break
        if len(candidates) < 2:
            continue
        by_hash, errors, cancelled = hash_project_candidates(
            candidates,
            workers=hash_workers,
            cancel_event=cancel_event,
        )
        if cancelled:
            break
        for digest, files in by_hash.items():
            if len(files) < 2:
                continue
            keeper = min(files, key=lambda item: path_priority(item, root))
            for file in sorted(files, key=lambda item: str(item).lower()):
                if file == keeper:
                    continue
                target = duplicate_quarantine_target(root, file, digest)
                operations.append(
                    DuplicateOperation(
                        source=str(file),
                        destination=str(target),
                        keeper=str(keeper),
                        sha256=digest,
                        size=size,
                        reason="duplicado exato: mesmo tamanho e SHA-256",
                    )
                )
    return operations, skipped_cad


def drive_type(path: str) -> int:
    if os.name != "nt":
        return 0
    return ctypes.windll.kernel32.GetDriveTypeW(str(path))


def discover_external_drives(root: Path, *, include_fixed: bool = False) -> list[Path]:
    if os.name != "nt":
        return []
    root_drive = root.drive.upper()
    drives: list[Path] = []
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        drive = Path(f"{letter}:\\")
        if not drive.exists():
            continue
        dtype = drive_type(str(drive))
        if drive.drive.upper() == root_drive:
            continue
        if dtype == 2 or (include_fixed and dtype == 3 and letter != "C"):
            drives.append(drive)
    return drives


def candidate_score(path: Path) -> tuple[int, list[str]]:
    text = canonical_text(str(path))
    suffix = path.suffix.lower()
    score = 0
    reasons: list[str] = []
    keywords = {
        "ramtech": 5,
        "macrotec": 5,
        "opcao": 5,
        "opcao industrial": 7,
        "catalogo opcao": 6,
        "codigos op": 6,
        "op ": 2,
        "op-": 3,
        "forno corning": 5,
        "eplan": 4,
        "solidworks": 4,
        "solid electrical": 4,
        "solid eletrical": 4,
        "solidworks electrical": 5,
        "projeto eletrico": 4,
        "projeto mecanico": 4,
        "qgbt": 4,
        "painel": 3,
        "c200": 3,
        "p200": 3,
        "p210": 3,
        "plc": 2,
        "sldprt": 3,
        "sldasm": 3,
        "slddrw": 3,
    }
    for keyword, value in keywords.items():
        if keyword in text:
            score += value
            reasons.append(keyword)
    if suffix in PROJECT_EXTENSIONS:
        score += 2
        reasons.append(f"extensao {suffix}")
    if is_cad_tree_file(path):
        score += 4
        reasons.append("metadado/arquivo CAD")
    if PROJECT_CODE_RE.search(path.name):
        score += 4
        reasons.append("codigo de projeto")
    if OPCAO_CODE_RE.search(path.name):
        score += 5
        reasons.append("codigo Opcao")
    return score, reasons


def import_target_for_external(root: Path, source: Path, drive: Path) -> Path:
    label = slug(drive.drive.replace(":", "") or drive.name)
    return state_path(root, EXTERNAL_INBOX_DIR, label) / safe_external_relative_path(source, drive)


def safe_external_relative_path(source: Path, drive: Path) -> Path:
    try:
        relative = source.relative_to(drive)
    except ValueError:
        relative = Path(source.name)
    parts = list(Path(relative).parts)
    if not parts:
        return Path(safe_filename(source.name))
    directory_parts = [slug(part) for part in parts[:-1]]
    return Path(*directory_parts, safe_filename(parts[-1]))


def external_family_base(root: Path, source: Path) -> Path:
    roots = canonical_roots(root)
    text = canonical_text(" ".join(source.parts))
    if "opcao" in text or "opcao industrial" in text or OPCAO_CODE_RE.search(source.name):
        return roots["opcao"] / "_popular_base"
    if "ramtech" in text or "macrotec" in text or PROJECT_CODE_RE.search(source.name):
        return roots["ramtech"] / "_popular_base"
    return roots["referencias"] / "_popular_base_revisar"


def populate_base_target_for_external(root: Path, source: Path, drive: Path) -> tuple[Path, str]:
    if not is_cad_protected_file(source):
        target, reason = classify_for_root(source, root)
        if target is not None:
            return target, f"popular base: {reason}"
    label = slug(drive.drive.replace(":", "") or drive.name)
    target = external_family_base(root, source) / label / safe_external_relative_path(source, drive)
    return target, "popular base: ausente na base; preservar arvore externa para revisao segura"


def size_index(paths: Iterable[Path]) -> dict[int, list[Path]]:
    indexed: dict[int, list[Path]] = {}
    for path in paths:
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size <= 0:
            continue
        indexed.setdefault(size, []).append(path)
    return indexed


def existing_file_match(
    source: Path,
    base_by_size: dict[int, list[Path]],
    digest_cache: dict[Path, str],
    *,
    cancel_event: threading.Event | None,
) -> tuple[Path | None, str | None]:
    try:
        source_size = source.stat().st_size
    except OSError:
        return None, None
    if source_size <= 0 or source_size not in base_by_size:
        return None, None

    source_digest = file_sha256(source, cancel_event=cancel_event)
    for candidate in base_by_size[source_size]:
        if is_cancelled(cancel_event):
            raise InterruptedError("operacao cancelada pelo usuario")
        try:
            candidate_digest = digest_cache.get(candidate)
            if candidate_digest is None:
                candidate_digest = file_sha256(candidate, cancel_event=cancel_event)
                digest_cache[candidate] = candidate_digest
        except OSError:
            continue
        if candidate_digest == source_digest:
            return candidate, source_digest
    return None, source_digest


def scan_external_candidates(
    root: Path,
    drives: Iterable[Path],
    *,
    min_score: int,
    max_files: int | None,
    base_files: list[Path] | None = None,
    populate_base: bool = False,
    cancel_event: threading.Event | None = None,
    warnings: list[str] | None = None,
) -> list[ExternalCandidate]:
    candidates: list[ExternalCandidate] = []
    base_by_size = size_index(base_files or []) if populate_base else {}
    digest_cache: dict[Path, str] = {}
    skipped_existing = 0
    for drive in drives:
        if is_cancelled(cancel_event):
            break
        for path in iter_files(drive, max_files=max_files):
            if is_cancelled(cancel_event):
                break
            score, reasons = candidate_score(path)
            if score < min_score:
                continue
            try:
                size = path.stat().st_size
            except OSError:
                if populate_base and warnings is not None:
                    warnings.append(f"nao foi possivel ler candidato externo: {path}")
                continue
            sha256: str | None = None
            duplicate_of: str | None = None
            if populate_base:
                try:
                    existing, sha256 = existing_file_match(
                        path,
                        base_by_size,
                        digest_cache,
                        cancel_event=cancel_event,
                    )
                except OSError as exc:
                    if warnings is not None:
                        warnings.append(f"nao foi possivel comparar {path}: {exc}")
                    continue
                if existing is not None:
                    skipped_existing += 1
                    continue
                destination, target_reason = populate_base_target_for_external(root, path, drive)
                decision = "popular_base"
                candidate_reasons = [*reasons, target_reason, "conteudo ausente na base atual"]
            else:
                destination = import_target_for_external(root, path, drive)
                decision = "copy_to_inbox"
                candidate_reasons = list(reasons)
            candidates.append(
                ExternalCandidate(
                    source=str(path),
                    destination=str(destination),
                    drive=str(drive),
                    score=score,
                    reasons=candidate_reasons,
                    size=size,
                    sha256=sha256,
                    duplicate_of=duplicate_of,
                    decision=decision,
                )
            )
    if skipped_existing and warnings is not None:
        warnings.append(f"{skipped_existing} candidato(s) externo(s) ignorado(s) porque ja existem na base")
    candidates.sort(key=lambda item: (-item.score, item.source.lower()))
    return candidates


def scan_projects(
    root: Path,
    *,
    external: bool = False,
    external_drives: list[Path] | None = None,
    include_fixed_external: bool = False,
    min_external_score: int = 7,
    max_files: int | None = None,
    max_hash_size_mb: int | None = 2048,
    no_hash: bool = False,
    include_cad_duplicates: bool = False,
    hash_workers: int = 1,
    populate_base: bool = False,
    cancel_event: threading.Event | None = None,
) -> ProjectReport:
    if not root.exists():
        raise FileNotFoundError(root)
    if not root.is_dir():
        raise NotADirectoryError(root)

    report = ProjectReport(root=str(root), generated_at=datetime.now().isoformat(timespec="seconds"))
    report.warnings.extend(learned_model_summary())
    if is_cancelled(cancel_event):
        report.warnings.append("operacao cancelada pelo usuario antes da previa")
        return report

    all_files: list[Path] = []
    if not is_cancelled(cancel_event):
        all_files = list(iter_files(root, max_files=max_files))
        for path in all_files:
            if is_cancelled(cancel_event):
                break
            summarize_file(path, root, report.file_summary, report.directory_summary)

    report.organization = build_organization_plan(root, cancel_event=cancel_event)
    if not no_hash:
        if is_cancelled(cancel_event):
            report.warnings.append("operacao cancelada pelo usuario antes da busca de duplicatas")
            return report
        report.duplicates, skipped_cad = find_duplicates(
            files_to_scan=all_files,
            root=root,
            max_size_mb=max_hash_size_mb,
            include_cad_duplicates=include_cad_duplicates,
            hash_workers=hash_workers,
            cancel_event=cancel_event,
        )
        if skipped_cad:
            report.warnings.append(
                f"{skipped_cad} arquivos CAD ignorados na quarentena de duplicatas para preservar referencias"
            )
        if is_cancelled(cancel_event):
            report.warnings.append("operacao cancelada pelo usuario durante a busca de duplicatas")
            return report
    if external:
        drives = external_drives or discover_external_drives(root, include_fixed=include_fixed_external)
        if not drives:
            report.warnings.append("nenhum drive externo/removivel encontrado para varredura")
        else:
            roots = canonical_roots(root)
            base_files = [path for path in all_files if is_inside_any(path, [roots["base"]])]
            report.external_candidates = scan_external_candidates(
                root,
                drives,
                min_score=min_external_score,
                max_files=max_files,
                base_files=base_files,
                populate_base=populate_base,
                cancel_event=cancel_event,
                warnings=report.warnings,
            )
    return report


def write_report(report: ProjectReport, output_dir: Path) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = now_stamp()
    json_path = output_dir / f"projetos-report-{stamp}.json"
    csv_path = output_dir / f"projetos-operacoes-{stamp}.csv"
    md_path = output_dir / f"projetos-resumo-{stamp}.md"

    json_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["section", "source", "destination", "reason", "decision", "duplicate_of", "sha256", "extra"])
        for item in report.organization:
            writer.writerow(["organization", item.source, item.destination, item.reason, item.action, "", "", ""])
        for item in report.duplicates:
            writer.writerow(
                ["duplicates", item.source, item.destination, item.reason, "move_duplicate", item.keeper, item.sha256, ""]
            )
        for item in report.external_candidates:
            writer.writerow(
                [
                    "external",
                    item.source,
                    item.destination,
                    "; ".join(item.reasons),
                    item.decision,
                    item.duplicate_of or "",
                    item.sha256 or "",
                    f"score={item.score}",
                ]
            )

    lines = [
        "# Relatorio Arruma Projetos",
        "",
        f"Raiz: `{report.root}`",
        f"Gerado em: `{report.generated_at}`",
        "",
        "## Estatisticas",
        "",
    ]
    for key, value in report.stats.items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Modelo aprendido", ""])
    for warning in report.warnings:
        lines.append(f"- {warning}")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, csv_path, md_path


def load_report(path: Path) -> ProjectReport:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return ProjectReport(
        root=payload["root"],
        generated_at=payload["generated_at"],
        organization=[MoveOperation(**item) for item in payload.get("organization", [])],
        duplicates=[DuplicateOperation(**item) for item in payload.get("duplicates", [])],
        external_candidates=[ExternalCandidate(**item) for item in payload.get("external_candidates", [])],
        warnings=payload.get("warnings", []),
        errors=payload.get("errors", []),
        file_summary=payload.get("file_summary", {}),
        directory_summary=payload.get("directory_summary", {}),
    )


def execute_move(source: Path, destination: Path, *, dry_run: bool) -> tuple[str, str]:
    if dry_run:
        return (str(source), str(destination))
    destination = unique_path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))
    return (str(source), str(destination))


def execute_merge_dir(source: Path, destination: Path, *, dry_run: bool) -> list[tuple[str, str]]:
    if not source.is_dir():
        raise NotADirectoryError(source)

    source_resolved = source.resolve(strict=False)
    destination_resolved = destination.resolve(strict=False)
    if source_resolved == destination_resolved:
        return []
    try:
        destination_resolved.relative_to(source_resolved)
    except ValueError:
        pass
    else:
        raise ValueError(f"Destino dentro da origem: {destination}")

    moved: list[tuple[str, str]] = []
    if not dry_run:
        destination.mkdir(parents=True, exist_ok=True)

    for child in sorted(source.iterdir(), key=lambda item: item.name.lower()):
        target = unique_path(destination / child.name)
        moved.append((str(child), str(target)))
        if dry_run:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(child), str(target))

    if not dry_run:
        try:
            source.rmdir()
        except OSError:
            pass
    return moved


def execute_copy(source: Path, destination: Path, *, dry_run: bool) -> tuple[str, str]:
    if dry_run:
        return (str(source), str(destination))
    destination = unique_path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(source), str(destination))
    return (str(source), str(destination))


def apply_report(
    report: ProjectReport,
    *,
    organize: bool,
    duplicates: bool,
    import_external: bool,
    yes: bool,
    cancel_event: threading.Event | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> ProjectApplyResult:
    root = Path(report.root)
    dry_run = not yes
    result: ProjectApplyResult = {
        "moved": [],
        "copied": [],
        "skipped": [],
        "errors": [],
        "moved_pairs": [],
        "copied_pairs": [],
    }

    total_items = 0
    if organize:
        total_items += len(report.organization)
    if duplicates:
        total_items += len(report.duplicates)
    if import_external:
        total_items += len(report.external_candidates)

    processed_items = 0

    if organize:
        for item in report.organization:
            processed_items += 1
            if progress_callback:
                progress_callback(processed_items, total_items)
            if is_cancelled(cancel_event):
                raise InterruptedError("Organizacao de projetos cancelada pelo usuario.")
            source = Path(item.source)
            destination = Path(item.destination)
            try:
                ensure_inside(root, destination)
                if not source.exists():
                    result["skipped"].append(f"nao existe: {source}")
                    continue
                if item.action == "merge_dir":
                    moved_items = execute_merge_dir(source, destination, dry_run=dry_run)
                    for moved in moved_items:
                        result["moved"].append(f"{moved[0]} -> {moved[1]}")
                    result["moved_pairs"].extend(moved_items)
                elif item.action == "move":
                    moved = execute_move(source, destination, dry_run=dry_run)
                    result["moved"].append(f"{moved[0]} -> {moved[1]}")
                    result["moved_pairs"].append(moved)
                else:
                    result["skipped"].append(f"acao desconhecida: {item.action} em {source}")
            except Exception as exc:  # noqa: BLE001
                result["errors"].append(f"{source}: {exc}")

    if duplicates:
        for item in report.duplicates:
            processed_items += 1
            if progress_callback:
                progress_callback(processed_items, total_items)
            if is_cancelled(cancel_event):
                raise InterruptedError("Movimentacao de duplicatas de projetos cancelada.")
            source = Path(item.source)
            destination = Path(item.destination)
            try:
                ensure_inside(root, destination)
                if not source.exists():
                    result["skipped"].append(f"nao existe: {source}")
                    continue
                moved = execute_move(source, destination, dry_run=dry_run)
                result["moved"].append(f"{moved[0]} -> {moved[1]}")
                result["moved_pairs"].append(moved)
            except Exception as exc:  # noqa: BLE001
                result["errors"].append(f"{source}: {exc}")

    if import_external:
        for item in report.external_candidates:
            processed_items += 1
            if progress_callback:
                progress_callback(processed_items, total_items)
            if is_cancelled(cancel_event):
                raise InterruptedError("Importacao de arquivos externos cancelada.")
            source = Path(item.source)
            destination = Path(item.destination)
            try:
                ensure_inside(root, destination)
                if not source.exists():
                    result["skipped"].append(f"nao existe: {source}")
                    continue
                copied = execute_copy(source, destination, dry_run=dry_run)
                result["copied"].append(f"{copied[0]} -> {copied[1]}")
                result["copied_pairs"].append(copied)
            except Exception as exc:  # noqa: BLE001
                result["errors"].append(f"{source}: {exc}")

    return result


def create_project_template(root: Path, name: str, *, yes: bool) -> list[str]:
    project_root = canonical_roots(root)["ramtech_projetos"] / name
    created: list[str] = []
    for folder in RAMTECH_PROJECT_SUBFOLDERS:
        target = project_root / folder
        if yes:
            target.mkdir(parents=True, exist_ok=True)
        created.append(str(target))
    return created


def create_opcao_template(root: Path, name: str, *, yes: bool) -> list[str]:
    project_root = canonical_roots(root)["opcao_mecanico"] / name
    created: list[str] = []
    for folder in OPCAO_PROJECT_SUBFOLDERS:
        target = project_root / folder
        if yes:
            target.mkdir(parents=True, exist_ok=True)
        created.append(str(target))
    return created
