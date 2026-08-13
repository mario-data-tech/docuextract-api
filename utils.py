"""
utils.py
--------
Módulo de utilidades para DocuExtract API.

Contiene:
    - Esquemas Pydantic para validar la salida estructurada de OpenAI.
    - Funciones de extracción de texto/imágenes desde PDFs (digitales o escaneados).
    - Cliente robusto de interacción con la API de OpenAI (GPT-4o + JSON Mode).
    - Excepciones personalizadas para un manejo de errores claro en la capa de UI.

Autor: Mario Data Tech
"""

from __future__ import annotations

import base64
import io
import json
import logging
from enum import Enum
from typing import Any, Dict, List, Optional

import pdfplumber
from openai import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)
from pdf2image import convert_from_bytes
from pydantic import BaseModel, Field, ValidationError

# --------------------------------------------------------------------------- #
# Configuración de logging
# --------------------------------------------------------------------------- #
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("docuextract")

# Umbral mínimo de caracteres para considerar que el PDF tiene texto "extraíble".
# Por debajo de este umbral se asume que el PDF está escaneado (imagen pura)
# y se recurre a visión por computador (GPT-4o Vision) en lugar de texto plano.
MIN_TEXT_LENGTH_THRESHOLD = 40

# Máximo de páginas que se convierten a imagen para evitar costos/latencia excesivos.
MAX_PAGES_TO_PROCESS = 8

# Modelo de OpenAI utilizado. GPT-4o soporta Vision + JSON Mode de forma nativa.
OPENAI_MODEL = "gpt-4o"


# --------------------------------------------------------------------------- #
# Excepciones personalizadas
# --------------------------------------------------------------------------- #
class DocuExtractError(Exception):
    """Excepción base para errores controlados de la aplicación."""


class PDFCorruptoError(DocuExtractError):
    """Se lanza cuando el archivo PDF no puede leerse o está dañado."""


class APIKeyInvalidaError(DocuExtractError):
    """Se lanza cuando la API Key de OpenAI es inválida o fue rechazada."""


class LimiteExcedidoError(DocuExtractError):
    """Se lanza cuando se excede el límite de solicitudes (rate limit) de OpenAI."""


class ExtraccionFallidaError(DocuExtractError):
    """Se lanza cuando OpenAI responde pero el JSON no cumple el esquema esperado."""


# --------------------------------------------------------------------------- #
# Tipos de documento soportados
# --------------------------------------------------------------------------- #
class TipoDocumento(str, Enum):
    FACTURA = "Factura"
    CONTRATO = "Contrato"
    ESCRITURA = "Escritura"
    GENERICO = "Genérico"


# --------------------------------------------------------------------------- #
# Esquemas Pydantic (uno por tipo de documento)
# --------------------------------------------------------------------------- #
class ItemFactura(BaseModel):
    """Línea de detalle dentro de una factura."""

    descripcion: str = Field(..., description="Descripción del producto o servicio")
    cantidad: Optional[float] = Field(None, description="Cantidad facturada")
    precio_unitario: Optional[float] = Field(None, description="Precio unitario sin impuestos")
    subtotal: Optional[float] = Field(None, description="Subtotal de la línea")


class EsquemaFactura(BaseModel):
    """Esquema estricto para la extracción de datos de una factura."""

    tipo_documento: str = Field(default="Factura")
    numero_factura: Optional[str] = Field(None, description="Número o folio de la factura")
    fecha_emision: Optional[str] = Field(None, description="Fecha de emisión (YYYY-MM-DD)")
    fecha_vencimiento: Optional[str] = Field(None, description="Fecha de vencimiento (YYYY-MM-DD)")
    emisor_nombre: Optional[str] = Field(None, description="Nombre o razón social del emisor")
    emisor_identificacion_fiscal: Optional[str] = Field(None, description="CUIT/RFC/NIF del emisor")
    receptor_nombre: Optional[str] = Field(None, description="Nombre o razón social del receptor")
    receptor_identificacion_fiscal: Optional[str] = Field(None, description="CUIT/RFC/NIF del receptor")
    moneda: Optional[str] = Field(None, description="Moneda de la transacción, ej. ARS, USD")
    items: List[ItemFactura] = Field(default_factory=list, description="Detalle de ítems facturados")
    subtotal: Optional[float] = Field(None, description="Subtotal antes de impuestos")
    impuestos: Optional[float] = Field(None, description="Monto total de impuestos")
    total: Optional[float] = Field(None, description="Monto total de la factura")
    metodo_pago: Optional[str] = Field(None, description="Método de pago indicado")
    observaciones: Optional[str] = Field(None, description="Notas u observaciones adicionales")


class EsquemaContrato(BaseModel):
    """Esquema estricto para la extracción de datos de un contrato."""

    tipo_documento: str = Field(default="Contrato")
    titulo_contrato: Optional[str] = Field(None, description="Título o tipo de contrato")
    fecha_firma: Optional[str] = Field(None, description="Fecha de firma (YYYY-MM-DD)")
    lugar_firma: Optional[str] = Field(None, description="Lugar donde se firmó el contrato")
    parte_a_nombre: Optional[str] = Field(None, description="Nombre de la primera parte")
    parte_a_identificacion: Optional[str] = Field(None, description="Identificación fiscal/DNI de la parte A")
    parte_b_nombre: Optional[str] = Field(None, description="Nombre de la segunda parte")
    parte_b_identificacion: Optional[str] = Field(None, description="Identificación fiscal/DNI de la parte B")
    objeto_contrato: Optional[str] = Field(None, description="Descripción del objeto/propósito del contrato")
    duracion: Optional[str] = Field(None, description="Duración o vigencia del contrato")
    monto: Optional[float] = Field(None, description="Monto económico involucrado, si aplica")
    moneda: Optional[str] = Field(None, description="Moneda del monto, ej. ARS, USD")
    clausulas_clave: List[str] = Field(default_factory=list, description="Cláusulas relevantes resumidas")
    jurisdiccion: Optional[str] = Field(None, description="Jurisdicción o ley aplicable")
    observaciones: Optional[str] = Field(None, description="Notas u observaciones adicionales")


class EsquemaEscritura(BaseModel):
    """Esquema estricto para la extracción de datos de una escritura pública."""

    tipo_documento: str = Field(default="Escritura")
    numero_escritura: Optional[str] = Field(None, description="Número de escritura/protocolo")
    fecha_otorgamiento: Optional[str] = Field(None, description="Fecha de otorgamiento (YYYY-MM-DD)")
    escribano_nombre: Optional[str] = Field(None, description="Nombre del escribano/notario")
    registro_notarial: Optional[str] = Field(None, description="Número de registro notarial")
    otorgante_nombre: Optional[str] = Field(None, description="Nombre del otorgante/vendedor")
    adquirente_nombre: Optional[str] = Field(None, description="Nombre del adquirente/comprador")
    descripcion_inmueble: Optional[str] = Field(None, description="Descripción del inmueble o bien")
    matricula_catastral: Optional[str] = Field(None, description="Matrícula o partida catastral")
    superficie: Optional[str] = Field(None, description="Superficie del inmueble (con unidad)")
    monto_operacion: Optional[float] = Field(None, description="Monto de la operación")
    moneda: Optional[str] = Field(None, description="Moneda del monto, ej. ARS, USD")
    gravamenes: Optional[str] = Field(None, description="Gravámenes o restricciones informadas")
    observaciones: Optional[str] = Field(None, description="Notas u observaciones adicionales")


class EsquemaGenerico(BaseModel):
    """Esquema flexible para documentos que no encajan en una categoría predefinida."""

    tipo_documento: str = Field(default="Genérico")
    titulo: Optional[str] = Field(None, description="Título o asunto principal del documento")
    fecha: Optional[str] = Field(None, description="Fecha relevante del documento (YYYY-MM-DD)")
    entidades_mencionadas: List[str] = Field(default_factory=list, description="Personas u organizaciones mencionadas")
    resumen: Optional[str] = Field(None, description="Resumen ejecutivo del contenido en 3-5 líneas")
    datos_clave: Dict[str, str] = Field(default_factory=dict, description="Pares clave-valor de datos relevantes detectados")
    observaciones: Optional[str] = Field(None, description="Notas u observaciones adicionales")


# Mapeo entre el tipo de documento seleccionado en la UI y su esquema Pydantic.
ESQUEMAS_POR_TIPO: Dict[TipoDocumento, type[BaseModel]] = {
    TipoDocumento.FACTURA: EsquemaFactura,
    TipoDocumento.CONTRATO: EsquemaContrato,
    TipoDocumento.ESCRITURA: EsquemaEscritura,
    TipoDocumento.GENERICO: EsquemaGenerico,
}


# --------------------------------------------------------------------------- #
# Procesamiento de PDF
# --------------------------------------------------------------------------- #
def extraer_texto_pdf(pdf_bytes: bytes) -> str:
    """
    Intenta extraer texto plano de un PDF digital usando pdfplumber.

    Args:
        pdf_bytes: Contenido binario del PDF.

    Returns:
        Texto extraído concatenado de todas las páginas (puede ser cadena vacía
        si el PDF es una imagen escaneada sin capa de texto).

    Raises:
        PDFCorruptoError: si el archivo no puede abrirse como PDF válido.
    """
    try:
        texto_completo: List[str] = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for pagina in pdf.pages:
                texto_pagina = pagina.extract_text() or ""
                texto_completo.append(texto_pagina)
        return "\n".join(texto_completo).strip()
    except Exception as exc:  # pdfplumber puede lanzar varias excepciones internas
        logger.error("Error al extraer texto del PDF: %s", exc)
        raise PDFCorruptoError(
            "No se pudo leer el PDF. El archivo podría estar dañado, protegido "
            "con contraseña o no ser un PDF válido."
        ) from exc


def convertir_pdf_a_imagenes_base64(pdf_bytes: bytes, max_paginas: int = MAX_PAGES_TO_PROCESS) -> List[str]:
    """
    Convierte cada página de un PDF (típicamente escaneado) a una imagen PNG
    codificada en base64, lista para enviarse a GPT-4o Vision.

    Args:
        pdf_bytes: Contenido binario del PDF.
        max_paginas: Límite de páginas a convertir por control de costo/latencia.

    Returns:
        Lista de strings base64 (una por página procesada).

    Raises:
        PDFCorruptoError: si `pdf2image` no logra renderizar el PDF (por ejemplo,
            si el binario `poppler-utils` no está instalado en el sistema, o el
            archivo está corrupto).
    """
    try:
        imagenes = convert_from_bytes(pdf_bytes, dpi=200, fmt="png")
    except Exception as exc:
        logger.error("Error al convertir PDF a imágenes: %s", exc)
        raise PDFCorruptoError(
            "No se pudo renderizar el PDF como imagen. Verificá que el archivo "
            "no esté corrupto y que 'poppler' esté instalado en el sistema."
        ) from exc

    imagenes = imagenes[:max_paginas]
    imagenes_base64: List[str] = []
    for img in imagenes:
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
        imagenes_base64.append(b64)
    return imagenes_base64


def documento_requiere_vision(texto_extraido: str) -> bool:
    """
    Determina heurísticamente si un PDF necesita ser tratado como imagen
    (documento escaneado) en lugar de texto plano.
    """
    return len(texto_extraido.strip()) < MIN_TEXT_LENGTH_THRESHOLD


# --------------------------------------------------------------------------- #
# Construcción de prompts
# --------------------------------------------------------------------------- #
def construir_prompt_sistema(tipo_documento: TipoDocumento) -> str:
    """Genera el prompt de sistema adaptado al tipo de documento seleccionado."""
    return (
        "Sos un asistente experto en extracción de datos estructurados a partir de "
        f"documentos de tipo '{tipo_documento.value}'. Tu tarea es leer el contenido "
        "(texto o imagen) del documento provisto y devolver EXCLUSIVAMENTE un objeto "
        "JSON que cumpla estrictamente el esquema indicado por la herramienta de "
        "salida estructurada. Reglas:\n"
        "1. Si un dato no aparece en el documento, usá null en lugar de inventarlo.\n"
        "2. Normalizá las fechas al formato YYYY-MM-DD cuando sea posible.\n"
        "3. Normalizá los montos como números (sin símbolos de moneda ni separadores de miles).\n"
        "4. No agregues texto, explicaciones ni comentarios fuera del JSON.\n"
        "5. Mantené el idioma original de los textos libres (resúmenes, observaciones) en español."
    )


# --------------------------------------------------------------------------- #
# Cliente OpenAI
# --------------------------------------------------------------------------- #
def _construir_mensaje_usuario(
    texto_pdf: str,
    imagenes_base64: Optional[List[str]],
) -> List[Dict[str, Any]]:
    """
    Construye el contenido del mensaje de usuario para la API de OpenAI,
    combinando texto y/o imágenes según lo que esté disponible.
    """
    contenido: List[Dict[str, Any]] = []

    instruccion = (
        "Extraé los datos estructurados del siguiente documento y devolvé "
        "únicamente el JSON solicitado."
    )
    contenido.append({"type": "text", "text": instruccion})

    if texto_pdf:
        contenido.append({"type": "text", "text": f"Texto extraído del PDF:\n\n{texto_pdf}"})

    if imagenes_base64:
        for b64 in imagenes_base64:
            contenido.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"},
                }
            )

    return contenido


def extraer_datos_con_openai(
    api_key: str,
    tipo_documento: TipoDocumento,
    texto_pdf: str,
    imagenes_base64: Optional[List[str]] = None,
    modelo: str = OPENAI_MODEL,
) -> Dict[str, Any]:
    """
    Envía el contenido del documento a GPT-4o y devuelve el JSON validado
    contra el esquema Pydantic correspondiente al tipo de documento.

    Args:
        api_key: API Key de OpenAI.
        tipo_documento: Tipo de documento seleccionado en la UI.
        texto_pdf: Texto plano extraído del PDF (puede ser cadena vacía).
        imagenes_base64: Lista de imágenes en base64 si el documento es escaneado.
        modelo: Nombre del modelo de OpenAI a utilizar.

    Returns:
        Diccionario con los datos extraídos, ya validados por Pydantic.

    Raises:
        APIKeyInvalidaError: si la API Key es inválida o fue rechazada.
        LimiteExcedidoError: si se excede el límite de solicitudes de OpenAI.
        ExtraccionFallidaError: si la respuesta no cumple el esquema esperado
            o si ocurre un error de comunicación con la API.
    """
    esquema_pydantic = ESQUEMAS_POR_TIPO[tipo_documento]

    try:
        client = OpenAI(api_key=api_key)

        mensajes = [
            {"role": "system", "content": construir_prompt_sistema(tipo_documento)},
            {"role": "user", "content": _construir_mensaje_usuario(texto_pdf, imagenes_base64)},
        ]

        # Usamos el modo "Structured Outputs" (response_format con json_schema)
        # para forzar a GPT-4o a devolver un JSON que cumpla el esquema Pydantic.
        respuesta = client.chat.completions.create(
            model=modelo,
            messages=mensajes,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": esquema_pydantic.__name__,
                    "schema": esquema_pydantic.model_json_schema(),
                    "strict": False,
                },
            },
            temperature=0.1,
            max_tokens=2000,
        )

        contenido_json = respuesta.choices[0].message.content
        datos_dict = json.loads(contenido_json)

        # Validación final contra el esquema Pydantic (defensa en profundidad,
        # por si el modelo se desvía levemente del schema declarado).
        objeto_validado = esquema_pydantic.model_validate(datos_dict)
        return objeto_validado.model_dump()

    except AuthenticationError as exc:
        logger.error("API Key inválida: %s", exc)
        raise APIKeyInvalidaError(
            "La API Key de OpenAI es inválida o no tiene permisos suficientes. "
            "Verificá la clave en la barra lateral."
        ) from exc

    except RateLimitError as exc:
        logger.error("Límite de solicitudes excedido: %s", exc)
        raise LimiteExcedidoError(
            "Se alcanzó el límite de solicitudes de OpenAI (rate limit) o la "
            "cuota disponible. Esperá unos minutos o revisá tu plan de facturación."
        ) from exc

    except APIConnectionError as exc:
        logger.error("Error de conexión con OpenAI: %s", exc)
        raise ExtraccionFallidaError(
            "No se pudo establecer conexión con la API de OpenAI. Verificá tu "
            "conexión a internet e intentá nuevamente."
        ) from exc

    except APIError as exc:
        logger.error("Error genérico de la API de OpenAI: %s", exc)
        raise ExtraccionFallidaError(
            f"OpenAI devolvió un error al procesar el documento: {exc}"
        ) from exc

    except (json.JSONDecodeError, ValidationError) as exc:
        logger.error("La respuesta de OpenAI no cumple el esquema esperado: %s", exc)
        raise ExtraccionFallidaError(
            "El modelo devolvió una respuesta que no pudo validarse contra el "
            "esquema esperado. Intentá nuevamente o probá con otro tipo de documento."
        ) from exc

    except Exception as exc:  # Red de seguridad final ante errores no previstos
        logger.error("Error inesperado durante la extracción: %s", exc)
        raise ExtraccionFallidaError(f"Ocurrió un error inesperado: {exc}") from exc


# --------------------------------------------------------------------------- #
# Pipeline de alto nivel (orquestador)
# --------------------------------------------------------------------------- #
def procesar_pdf(
    api_key: str,
    tipo_documento: TipoDocumento,
    pdf_bytes: bytes,
) -> Dict[str, Any]:
    """
    Orquesta el pipeline completo: extracción de texto/imágenes del PDF y
    llamada a OpenAI para obtener el JSON estructurado final.

    Esta es la función principal que debe invocar la capa de UI (app.py).

    Args:
        api_key: API Key de OpenAI provista por el usuario.
        tipo_documento: Tipo de documento seleccionado.
        pdf_bytes: Contenido binario del PDF subido.

    Returns:
        Diccionario con los datos extraídos y normalizados.
    """
    if not api_key or not api_key.strip():
        raise APIKeyInvalidaError("No se proporcionó una API Key de OpenAI válida.")

    if not pdf_bytes:
        raise PDFCorruptoError("El archivo subido está vacío o no pudo leerse.")

    texto_pdf = extraer_texto_pdf(pdf_bytes)
    imagenes_base64: Optional[List[str]] = None

    if documento_requiere_vision(texto_pdf):
        logger.info("PDF detectado como escaneado. Usando modo Vision.")
        imagenes_base64 = convertir_pdf_a_imagenes_base64(pdf_bytes)
        texto_pdf = ""  # Evitamos enviar texto ruidoso/irrelevante junto a las imágenes
    else:
        logger.info("PDF detectado como digital. Usando extracción de texto.")

    return extraer_datos_con_openai(
        api_key=api_key,
        tipo_documento=tipo_documento,
        texto_pdf=texto_pdf,
        imagenes_base64=imagenes_base64,
    )
