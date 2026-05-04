"""
Funciones auxiliares generales.
"""

from pathlib import Path


def check_paths(paths: list[str | Path]) -> dict:
    """Verifica la existencia de una lista de rutas."""
    return {str(path): Path(path).exists() for path in paths}
