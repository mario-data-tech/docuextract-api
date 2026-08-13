"""
app.py
------
DocuExtract API — Aplicación Streamlit para extracción automática de datos
estructurados desde documentos PDF (facturas, contratos, escrituras, etc.)
usando GPT-4o (Vision + JSON Mode).

Ejecución local:
    streamlit run app.py

Autor: Mario Data Tech
"""

from __future__ import annotations

import json
import os
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv

from utils import (
    APIKeyInvalidaError,
    DocuExtractError,
    ExtraccionFallidaError,
    LimiteExcedidoError,
    PDFCorruptoError,
    TipoDocumento,
    procesar_pdf,
)

# --------------------------------------------------------------------------- #
# Configuración inicial
# --------------------------------------------------------------------------- #
load_dotenv()  # Carga variables desde un archivo .env en desarrollo local

st.set_page_config(
    page_title="DocuExtract API",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)


def obtener_api_key_por_defecto() -> str:
    """
    Resuelve la API Key de OpenAI siguiendo este orden de prioridad:
        1. st.secrets (recomendado en Streamlit Community Cloud)
        2. Variable de entorno OPENAI_API_KEY (recomendado en local / Docker)
        3. Cadena vacía (el usuario deberá ingresarla manualmente en la UI)
    """
    try:
        if "OPENAI_API_KEY" in st.secrets:
            return st.secrets["OPENAI_API_KEY"]
    except Exception:
        # st.secrets lanza excepción si no existe secrets.toml; es un caso válido.
        pass
    return os.getenv("OPENAI_API_KEY", "")


# --------------------------------------------------------------------------- #
# Estilos personalizados (modo minimalista / profesional)
# --------------------------------------------------------------------------- #
CUSTOM_CSS = """
<style>
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
        max-width: 1100px;
    }
    div[data-testid="stMetric"] {
        background-color: #f8f9fb;
        border: 1px solid #e6e6e6;
        border-radius: 12px;
        padding: 1rem;
    }
    .docuextract-header {
        font-size: 2.1rem;
        font-weight: 700;
        margin-bottom: 0;
    }
    .docuextract-subheader {
        color: #6b7280;
        font-size: 1.05rem;
        margin-top: 0.25rem;
        margin-bottom: 1.5rem;
    }
    .stButton>button {
        border-radius: 8px;
        font-weight: 600;
    }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Barra lateral: configuración
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.markdown("### ⚙️ Configuración")

    api_key_input = st.text_input(
        "OpenAI API Key",
        value=obtener_api_key_por_defecto(),
        type="password",
        help=(
            "Tu clave de la API de OpenAI. También podés definirla como variable "
            "de entorno OPENAI_API_KEY o en st.secrets al desplegar."
        ),
        placeholder="sk-...",
    )

    st.markdown("---")

    tipo_documento_seleccionado = st.selectbox(
        "Tipo de documento",
        options=list(TipoDocumento),
        format_func=lambda t: t.value,
        help="Adapta el esquema de extracción según el tipo de documento.",
    )

    st.markdown("---")
    st.markdown("### ℹ️ Acerca de")
    st.caption(
        "**DocuExtract API** convierte PDFs (digitales o escaneados) en JSON "
        "estructurado usando GPT-4o. Ideal para inmobiliarias, bufetes y "
        "estudios contables que procesan documentos en volumen."
    )
    st.caption("Desarrollado por Mario Data Tech")


# --------------------------------------------------------------------------- #
# Encabezado principal
# --------------------------------------------------------------------------- #
st.markdown('<p class="docuextract-header">📄 DocuExtract API</p>', unsafe_allow_html=True)
st.markdown(
    '<p class="docuextract-subheader">Extracción automática de datos estructurados '
    "desde PDFs mediante IA — sin carga manual, sin errores humanos.</p>",
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------- #
# Estado de sesión
# --------------------------------------------------------------------------- #
if "resultados" not in st.session_state:
    st.session_state["resultados"] = {}  # nombre_archivo -> dict con datos extraídos

# --------------------------------------------------------------------------- #
# Zona de carga de archivos
# --------------------------------------------------------------------------- #
col_upload, col_info = st.columns([2, 1])

with col_upload:
    archivos_subidos = st.file_uploader(
        "Arrastrá uno o más PDFs para procesar",
        type=["pdf"],
        accept_multiple_files=True,
        help="Soporta PDFs digitales (con texto) y PDFs escaneados (imágenes).",
    )

with col_info:
    st.metric("Documentos cargados", len(archivos_subidos) if archivos_subidos else 0)
    st.metric("Documentos procesados", len(st.session_state["resultados"]))

procesar_btn = st.button(
    "🚀 Procesar documentos",
    type="primary",
    use_container_width=True,
    disabled=not archivos_subidos,
)

# --------------------------------------------------------------------------- #
# Procesamiento
# --------------------------------------------------------------------------- #
if procesar_btn:
    if not api_key_input or not api_key_input.strip():
        st.error(
            "⚠️ No se detectó una API Key de OpenAI. Ingresá una en la barra "
            "lateral antes de continuar."
        )
    else:
        barra_progreso = st.progress(0.0, text="Iniciando procesamiento...")
        total = len(archivos_subidos)

        for indice, archivo in enumerate(archivos_subidos, start=1):
            barra_progreso.progress(
                (indice - 1) / total,
                text=f"Procesando '{archivo.name}' ({indice}/{total})...",
            )
            try:
                pdf_bytes = archivo.read()
                resultado = procesar_pdf(
                    api_key=api_key_input,
                    tipo_documento=tipo_documento_seleccionado,
                    pdf_bytes=pdf_bytes,
                )
                st.session_state["resultados"][archivo.name] = {
                    "datos": resultado,
                    "tipo": tipo_documento_seleccionado.value,
                    "procesado_en": datetime.now().isoformat(timespec="seconds"),
                    "error": None,
                }

            except APIKeyInvalidaError as exc:
                st.session_state["resultados"][archivo.name] = {"error": str(exc)}
                st.error(f"🔑 **{archivo.name}**: {exc}")
                break  # No tiene sentido seguir con una key inválida

            except LimiteExcedidoError as exc:
                st.session_state["resultados"][archivo.name] = {"error": str(exc)}
                st.error(f"⏳ **{archivo.name}**: {exc}")
                break  # El límite aplica a toda la cuenta, no solo a este archivo

            except PDFCorruptoError as exc:
                st.session_state["resultados"][archivo.name] = {"error": str(exc)}
                st.warning(f"📄 **{archivo.name}**: {exc}")
                continue  # Seguimos con el resto de los archivos

            except (ExtraccionFallidaError, DocuExtractError) as exc:
                st.session_state["resultados"][archivo.name] = {"error": str(exc)}
                st.warning(f"⚠️ **{archivo.name}**: {exc}")
                continue

            except Exception as exc:  # Red de seguridad ante errores no anticipados
                st.session_state["resultados"][archivo.name] = {"error": str(exc)}
                st.warning(f"❌ **{archivo.name}**: Error inesperado — {exc}")
                continue

        barra_progreso.progress(1.0, text="Procesamiento finalizado ✅")
        st.success("Procesamiento completado.")

# --------------------------------------------------------------------------- #
# Visualización de resultados
# --------------------------------------------------------------------------- #
resultados = st.session_state["resultados"]

if resultados:
    st.markdown("## 📊 Resultados")

    nombres_exitosos = [
        nombre for nombre, r in resultados.items() if r.get("error") is None
    ]
    nombres_con_error = [
        nombre for nombre, r in resultados.items() if r.get("error") is not None
    ]

    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Total procesados", len(resultados))
    col_b.metric("Exitosos", len(nombres_exitosos))
    col_c.metric("Con errores", len(nombres_con_error))

    st.markdown("---")

    for nombre_archivo, info in resultados.items():
        if info.get("error"):
            with st.expander(f"❌ {nombre_archivo} — Error en el procesamiento"):
                st.error(info["error"])
            continue

        with st.expander(f"✅ {nombre_archivo} — {info['tipo']}", expanded=False):
            tab_json, tab_resumen = st.tabs(["JSON completo", "Vista resumida"])

            with tab_json:
                st.json(info["datos"])

                json_str = json.dumps(info["datos"], ensure_ascii=False, indent=2)
                st.download_button(
                    label="⬇️ Descargar JSON",
                    data=json_str,
                    file_name=f"{os.path.splitext(nombre_archivo)[0]}_extraido.json",
                    mime="application/json",
                    key=f"download_{nombre_archivo}",
                )

            with tab_resumen:
                datos = info["datos"]
                # Mostramos los campos escalares (no listas/dicts) como tabla rápida
                campos_simples = {
                    k: v for k, v in datos.items()
                    if not isinstance(v, (list, dict)) and v is not None
                }
                if campos_simples:
                    st.table(
                        {
                            "Campo": list(campos_simples.keys()),
                            "Valor": [str(v) for v in campos_simples.values()],
                        }
                    )
                else:
                    st.info("No hay campos escalares para mostrar en este documento.")

    # Botón para descargar todos los resultados exitosos en un único JSON
    if nombres_exitosos:
        st.markdown("---")
        json_consolidado = json.dumps(
            {nombre: resultados[nombre]["datos"] for nombre in nombres_exitosos},
            ensure_ascii=False,
            indent=2,
        )
        st.download_button(
            label="⬇️ Descargar todos los resultados (JSON consolidado)",
            data=json_consolidado,
            file_name="docuextract_resultados.json",
            mime="application/json",
            use_container_width=True,
        )

    if st.button("🗑️ Limpiar resultados"):
        st.session_state["resultados"] = {}
        st.rerun()

else:
    st.info(
        "Subí uno o más archivos PDF y presioná **Procesar documentos** para "
        "comenzar la extracción automática de datos."
    )
