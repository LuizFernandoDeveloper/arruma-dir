from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


SYSTEM_FOLDER_NAMES = {
    "$recycle.bin",
    "program files",
    "program files (x86)",
    "programdata",
    "recovery",
    "system volume information",
    "windows",
}


@dataclass
class SafetyCheck:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def is_filesystem_root(path: Path) -> bool:
    resolved = path.resolve(strict=False)
    return resolved.parent == resolved


def check_organization_root(path: str | Path, *, mode: str) -> SafetyCheck:
    target = Path(path).expanduser()
    check = SafetyCheck()

    if not str(target).strip():
        check.errors.append("Escolha uma pasta antes de continuar.")
        return check

    if not target.exists():
        check.errors.append(f"A pasta nao existe: {target}")
        return check

    if not target.is_dir():
        check.errors.append(f"O caminho nao e uma pasta: {target}")
        return check

    resolved = target.resolve(strict=False)
    if is_filesystem_root(resolved):
        check.errors.append("Nao organize a raiz do disco. Escolha uma pasta especifica, como Documentos ou F:\\projetos.")

    parts = {part.lower() for part in resolved.parts}
    blocked_parts = sorted(parts.intersection(SYSTEM_FOLDER_NAMES))
    if blocked_parts:
        check.errors.append("Pasta de sistema bloqueada: " + ", ".join(blocked_parts))

    normalized_parts = {part.lower() for part in resolved.parts}
    if mode == "documents":
        if not {"documentos", "documents"}.intersection(normalized_parts):
            check.warnings.append("Modo Documentos/PARA foi pensado para uma pasta de documentos pessoais.")
    elif mode == "projects":
        if resolved.name.lower() != "projetos":
            check.warnings.append("Modo Projetos/CAD foi pensado para a raiz F:\\projetos ou uma copia de teste dela.")
    else:
        check.errors.append(f"Modo desconhecido: {mode}")

    return check
