from __future__ import annotations

import argparse
import csv
import ctypes
import hashlib
import json
import logging
import os
import re
import shutil
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from .logging_utils import close_logger, create_operation_logger


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


@dataclass
class ProjectReport:
    root: str
    generated_at: str
    organization: list[MoveOperation] = field(default_factory=list)
    duplicates: list[DuplicateOperation] = field(default_factory=list)
    external_candidates: list[ExternalCandidate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

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


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


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

    if path == roots["entrada"] or is_inside_any(path, [roots["entrada"]]):
        opcao_target, opcao_reason = classify_opcao(path, root)
        if opcao_target is not None:
            return opcao_target, opcao_reason
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

    if "modelo" in name_text and ("ramtech" in text or "macrotec" in text):
        return roots["ramtech_modelos"] / path.name, "modelo Ramtech/Macrotec"

    if PROJECT_CODE_RE.search(path.name) and ("ramtech" in text or "macrotec" in text):
        return roots["ramtech_projetos"] / path.name, "codigo de projeto Ramtech/Macrotec"

    return None, "sem regra segura"


def build_organization_plan(root: Path) -> list[MoveOperation]:
    operations: list[MoveOperation] = []
    roots = canonical_roots(root)
    scan_roots = [root, roots["entrada"]]
    if roots["entrada"].exists():
        for child in roots["entrada"].iterdir():
            if child.is_dir() and canonical_text(child.name) in {"4 projeto mecanico", "projeto mecanico"}:
                scan_roots.append(child)
    seen: set[Path] = set()

    for scan_root in scan_roots:
        if not scan_root.exists():
            continue
        if scan_root in seen:
            continue
        seen.add(scan_root)
        for entry in sorted(scan_root.iterdir(), key=lambda item: item.name.lower()):
            if entry.name.lower() in {"projetos", STATE_DIR.lower()}:
                continue
            if is_noise_file(entry):
                continue
            target, reason = classify_for_root(entry, root)
            if target is None:
                continue
            ensure_inside(root, target)
            operations.append(MoveOperation("move", str(entry), str(target), reason))
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
    root: Path,
    *,
    max_files: int | None,
    max_size_mb: int | None,
    include_cad_duplicates: bool = False,
) -> tuple[list[DuplicateOperation], int]:
    max_bytes = max_size_mb * 1024 * 1024 if max_size_mb else None
    by_size: dict[int, list[Path]] = {}
    skipped_cad = 0

    for path in iter_files(root, max_files=max_files):
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
        if len(candidates) < 2:
            continue
        by_hash: dict[str, list[Path]] = {}
        for candidate in candidates:
            try:
                by_hash.setdefault(file_sha256(candidate), []).append(candidate)
            except OSError:
                continue
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
    try:
        relative = source.relative_to(drive)
    except ValueError:
        relative = source.name
    label = slug(drive.drive.replace(":", "") or drive.name)
    safe_parts = [slug(part) for part in Path(relative).parts]
    return state_path(root, EXTERNAL_INBOX_DIR, label, *safe_parts)


def scan_external_candidates(
    root: Path,
    drives: Iterable[Path],
    *,
    min_score: int,
    max_files: int | None,
) -> list[ExternalCandidate]:
    candidates: list[ExternalCandidate] = []
    for drive in drives:
        for path in iter_files(drive, max_files=max_files):
            score, reasons = candidate_score(path)
            if score < min_score:
                continue
            try:
                size = path.stat().st_size
            except OSError:
                size = None
            candidates.append(
                ExternalCandidate(
                    source=str(path),
                    destination=str(import_target_for_external(root, path, drive)),
                    drive=str(drive),
                    score=score,
                    reasons=reasons,
                    size=size,
                )
            )
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
) -> ProjectReport:
    if not root.exists():
        raise FileNotFoundError(root)
    if not root.is_dir():
        raise NotADirectoryError(root)

    report = ProjectReport(root=str(root), generated_at=datetime.now().isoformat(timespec="seconds"))
    report.warnings.extend(learned_model_summary())
    report.organization = build_organization_plan(root)
    if not no_hash:
        report.duplicates, skipped_cad = find_duplicates(
            root,
            max_files=max_files,
            max_size_mb=max_hash_size_mb,
            include_cad_duplicates=include_cad_duplicates,
        )
        if skipped_cad:
            report.warnings.append(
                f"{skipped_cad} arquivos CAD ignorados na quarentena de duplicatas para preservar referencias"
            )
    if external:
        drives = external_drives or discover_external_drives(root, include_fixed=include_fixed_external)
        if not drives:
            report.warnings.append("nenhum drive externo/removivel encontrado para varredura")
        else:
            report.external_candidates = scan_external_candidates(
                root,
                drives,
                min_score=min_external_score,
                max_files=max_files,
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
        writer.writerow(["section", "source", "destination", "reason", "extra"])
        for item in report.organization:
            writer.writerow(["organization", item.source, item.destination, item.reason, ""])
        for item in report.duplicates:
            writer.writerow(["duplicates", item.source, item.destination, item.reason, f"keeper={item.keeper}"])
        for item in report.external_candidates:
            writer.writerow(["external", item.source, item.destination, "; ".join(item.reasons), f"score={item.score}"])

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
    )


def execute_move(source: Path, destination: Path, *, dry_run: bool) -> tuple[str, str]:
    if dry_run:
        return (str(source), str(destination))
    destination = unique_path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))
    return (str(source), str(destination))


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
) -> dict[str, list[str]]:
    root = Path(report.root)
    dry_run = not yes
    result: dict[str, list[str]] = {"moved": [], "copied": [], "skipped": [], "errors": []}

    if organize:
        for item in report.organization:
            source = Path(item.source)
            destination = Path(item.destination)
            try:
                ensure_inside(root, destination)
                if not source.exists():
                    result["skipped"].append(f"nao existe: {source}")
                    continue
                moved = execute_move(source, destination, dry_run=dry_run)
                result["moved"].append(f"{moved[0]} -> {moved[1]}")
            except Exception as exc:  # noqa: BLE001
                result["errors"].append(f"{source}: {exc}")

    if duplicates:
        for item in report.duplicates:
            source = Path(item.source)
            destination = Path(item.destination)
            try:
                ensure_inside(root, destination)
                if not source.exists():
                    result["skipped"].append(f"nao existe: {source}")
                    continue
                moved = execute_move(source, destination, dry_run=dry_run)
                result["moved"].append(f"{moved[0]} -> {moved[1]}")
            except Exception as exc:  # noqa: BLE001
                result["errors"].append(f"{source}: {exc}")

    if import_external:
        for item in report.external_candidates:
            source = Path(item.source)
            destination = Path(item.destination)
            try:
                ensure_inside(root, destination)
                if not source.exists():
                    result["skipped"].append(f"nao existe: {source}")
                    continue
                copied = execute_copy(source, destination, dry_run=dry_run)
                result["copied"].append(f"{copied[0]} -> {copied[1]}")
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


def log_project_apply(logger: logging.Logger | None, result: dict[str, list[str]]) -> None:
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


def print_result(result: dict[str, list[str]], *, limit: int | None = 30) -> None:
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
        if logger:
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
