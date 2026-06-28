"""
Funciones de entrada y salida para el proyecto PGBM - Actividad 1.
"""

from pathlib import Path


def get_project_root() -> Path:
    """Devuelve la ruta raíz del proyecto."""
    return Path(__file__).resolve().parents[1]


def ensure_directory(path: str | Path) -> Path:
    """Crea un directorio si no existe."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path
