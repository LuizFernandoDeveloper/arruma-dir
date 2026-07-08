from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path


DOCUMENTS_STATE_DIR = "_arruma_dir"
PROJECTS_STATE_DIR = "_arruma_projetos"


def timestamp_for_file() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def operation_log_dir(root: str | Path, mode: str) -> Path:
    state_dir = PROJECTS_STATE_DIR if mode == "projects" else DOCUMENTS_STATE_DIR
    return Path(root).expanduser() / state_dir / "logs"


def create_operation_logger(
    root: str | Path,
    *,
    mode: str,
    operation: str,
    console: bool = False,
) -> tuple[logging.Logger, Path]:
    log_dir = operation_log_dir(root, mode)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{operation}-{timestamp_for_file()}.log"

    logger = logging.getLogger(f"arruma_dir.{mode}.{operation}.{timestamp_for_file()}.{id(log_path)}")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger, log_path


def close_logger(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        handler.flush()
        handler.close()
        logger.removeHandler(handler)
