"""
Funciones preliminares para scoring multicriterio de aptitud.
Estas funciones se ampliarán en el Módulo 9.
"""


def clasificar_aptitud(score: float) -> str:
    """Clasifica un score numérico en una categoría de aptitud."""
    if score >= 80:
        return "Alta"
    if score >= 60:
        return "Media"
    if score >= 40:
        return "Baja"
    return "Revisión o descarte"
