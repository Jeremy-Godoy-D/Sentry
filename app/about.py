"""Identidad y respaldo local de la versión publicada."""
from pathlib import Path
import sys

APP_NAME = "Sentry"
APP_VERSION = "1.0.0"
UPDATE_REPOSITORY = "jacksonandresrosales/Sentry"
APP_AUTHORS = "Jackson Ocaña y Jeremy Godoy"
APP_DESCRIPTION = (
    "Auditoría de llamadas para una atención mejor informada. "
    "Sentry reúne grabaciones, transcripciones y evidencias en un solo lugar "
    "para facilitar la revisión y el seguimiento de cada caso."
)
APP_FEATURES = (
    ("Costes API", "Consulta el gasto estimado diario de transcripción y análisis, con colores por servicio, detalle por solicitud y tarifas aplicadas automáticamente."),
    ("Exportación de costes", "Exporta a Excel el resumen, los gastos diarios, todas las solicitudes del filtro y las tarifas de referencia y aplicadas."),
    ("Modelos recomendados", "Deepgram Nova-3 transcribe; Gemini 3.5 Flash o DeepSeek V4.1 Flash analizan. Los modelos admitidos quedan fijados en Configuración."),
    ("Configuración de Issabel", "La conexión SFTP reúne servidor, puerto, usuario, contraseña y carpeta remota en un solo formulario."),
    ("Interfaz", "Se eliminó el borde verde que aparecía junto al desplazamiento en Reportes y Costes API."),
)


def license_text() -> str:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    try:
        return (root / "LICENSE").read_text(encoding="utf-8")
    except OSError:
        return "No se pudo cargar la licencia incluida con esta instalación."
