"""Identidad y respaldo local de la versión publicada."""
from pathlib import Path
import sys

APP_NAME = "Sentry"
APP_VERSION = "1.0.1"
UPDATE_REPOSITORY = "jacksonandresrosales/Sentry"
APP_AUTHORS = "Jackson Ocaña y Jeremy Godoy"
APP_DESCRIPTION = (
    "Auditoría de llamadas para una atención mejor informada. "
    "Sentry reúne grabaciones, transcripciones y evidencias en un solo lugar "
    "para facilitar la revisión y el seguimiento de cada caso."
)
APP_FEATURES = (
    ("Groq para análisis", "En Configuración, Otros proveedores permite seleccionar Groq GPT-OSS 120B para el análisis contextual de las llamadas."),
    ("Modelo y clave", "El modelo queda fijado para evitar errores de compatibilidad; Sentry valida la clave de Groq y la guarda cifrada con Windows."),
    ("Costes API", "La pantalla y el Excel incluyen las solicitudes de Groq con tarifas de referencia. En el plan gratuito puede no existir un cargo real."),
)


def license_text() -> str:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    try:
        return (root / "LICENSE").read_text(encoding="utf-8")
    except OSError:
        return "No se pudo cargar la licencia incluida con esta instalación."
