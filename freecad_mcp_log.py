"""
freecad_mcp_log.py — Logging centralizado para el bridge mcp-free-cad-.

Escribe a ~/.cache/freecad-mcp/logs/mcp.log (rotativo) y opcionalmente a stdout.
Uso:
    from freecad_mcp_log import get_logger
    log = get_logger(__name__)
    log.info("mensaje")
    log.error("algo fallo: %s", detalle)
"""
import logging
import logging.handlers
import os
from pathlib import Path

_LOG_DIR = Path.home() / ".cache" / "freecad-mcp" / "logs"
_LOG_FILE = _LOG_DIR / "mcp.log"
_MAX_BYTES = 5 * 1024 * 1024  # 5 MB por archivo
_BACKUP_COUNT = 3

_configured = False


def _configure_root():
    global _configured
    if _configured:
        return
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("freecad_mcp")
    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.handlers.RotatingFileHandler(
        _LOG_FILE, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    # Nivel de consola configurable via env var (default WARNING, para no
    # ensuciar stdout/stderr del proceso MCP salvo que se pida explicitamente)
    console_level_name = os.environ.get("FREECAD_MCP_CONSOLE_LOG_LEVEL", "WARNING")
    console_level = getattr(logging, console_level_name.upper(), logging.WARNING)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(fmt)
    root.addHandler(console_handler)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Devuelve un logger hijo de 'freecad_mcp', configurado con handlers
    de archivo (rotativo, siempre DEBUG) y consola (nivel via
    FREECAD_MCP_CONSOLE_LOG_LEVEL, default WARNING)."""
    _configure_root()
    return logging.getLogger(f"freecad_mcp.{name}")


def get_log_file_path() -> Path:
    """Ruta al archivo de log activo, para que otras herramientas
    (ej. get_last_error) lo lean directamente."""
    return _LOG_FILE
