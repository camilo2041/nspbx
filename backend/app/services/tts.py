"""Generación de audio con voces neuronales gratuitas (edge-tts, sin API key).

Usa el mismo motor de voz que el "Leer en voz alta" de Microsoft Edge —
voces neuronales de buena calidad, con varias variantes de español
(España, México, Colombia, Argentina, etc.), sin necesidad de cuenta ni
API key.
"""

import edge_tts

# Español seleccionado a mano (edge_tts.list_voices() trae decenas de locales;
# nos quedamos con los hispanohablantes más relevantes).
SPANISH_VOICES = [
    {"id": "es-CO-GonzaloNeural", "label": "Gonzalo (Colombia, hombre)"},
    {"id": "es-CO-SalomeNeural", "label": "Salomé (Colombia, mujer)"},
    {"id": "es-MX-DaliaNeural", "label": "Dalia (México, mujer)"},
    {"id": "es-MX-JorgeNeural", "label": "Jorge (México, hombre)"},
    {"id": "es-AR-ElenaNeural", "label": "Elena (Argentina, mujer)"},
    {"id": "es-AR-TomasNeural", "label": "Tomás (Argentina, hombre)"},
    {"id": "es-ES-ElviraNeural", "label": "Elvira (España, mujer)"},
    {"id": "es-ES-AlvaroNeural", "label": "Álvaro (España, hombre)"},
    {"id": "es-US-PalomaNeural", "label": "Paloma (Latino EE.UU., mujer)"},
    {"id": "es-US-AlonsoNeural", "label": "Alonso (Latino EE.UU., hombre)"},
]


async def synthesize(text: str, voice: str) -> bytes:
    """Genera audio MP3 a partir de texto. Lanza ValueError si la voz no es válida."""
    if voice not in {v["id"] for v in SPANISH_VOICES}:
        raise ValueError("Voz no soportada")
    if not text.strip():
        raise ValueError("El texto no puede estar vacío")
    communicate = edge_tts.Communicate(text, voice)
    chunks = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            chunks.extend(chunk["data"])
    if not chunks:
        raise ValueError("No se pudo generar el audio (respuesta vacía del motor de voz)")
    return bytes(chunks)
