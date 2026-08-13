# 📄 DocuExtract API

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-1.38-FF4B4B?logo=streamlit&logoColor=white)
![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4o-412991?logo=openai&logoColor=white)
![License](https://img.shields.io/badge/Licencia-MIT-green)
![Status](https://img.shields.io/badge/Estado-Producción-success)

**Extracción automática de datos estructurados desde documentos PDF (facturas, contratos, escrituras) usando GPT-4o con Vision y Structured Outputs.**

Pensado para PyMEs que hoy procesan documentos manualmente: inmobiliarias, bufetes de abogados, estudios contables y cualquier equipo que reciba cientos de PDFs distintos y necesite convertirlos en datos limpios y normalizados sin intervención humana.

---

## 🧠 El problema

Las PyMEs reciben a diario decenas o cientos de PDFs con formatos completamente distintos entre sí (facturas de distintos proveedores, contratos, escrituras). Extraer esos datos a mano es lento, repetitivo y propenso a errores humanos.

## ✅ La solución

**DocuExtract API** es una aplicación web minimalista que permite arrastrar uno o más PDFs — digitales o escaneados — y obtener en segundos un **JSON limpio, validado y normalizado**, listo para integrarse a cualquier sistema (ERP, CRM, planillas, bases de datos).

- Soporta documentos **digitales** (con capa de texto) y **escaneados** (imagen pura), detectando automáticamente cuál estrategia usar.
- Usa **GPT-4o Vision + JSON Mode / Structured Outputs** para garantizar que la respuesta siempre cumpla un esquema estricto definido con Pydantic.
- Esquemas de extracción dedicados para **Factura**, **Contrato**, **Escritura** y un modo **Genérico** para cualquier otro documento.
- Descarga individual o consolidada de los resultados en formato JSON.

---

## 🏗️ Arquitectura

```
                ┌────────────────────┐
                │      app.py        │  ← Interfaz Streamlit (UI, estado, orquestación)
                │  (Streamlit UI)     │
                └─────────┬──────────┘
                          │
                          ▼
                ┌────────────────────┐
                │      utils.py       │  ← Lógica de negocio
                │  - Extracción PDF   │
                │  - Esquemas Pydantic│
                │  - Cliente OpenAI   │
                └─────────┬──────────┘
                          │
             ┌────────────┼─────────────┐
             ▼                          ▼
    ┌──────────────────┐      ┌──────────────────────┐
    │ pdfplumber /      │      │   OpenAI API          │
    │ pdf2image          │      │   (GPT-4o + Vision +  │
    │ (extracción local) │      │    JSON Schema mode)  │
    └──────────────────┘      └──────────────────────┘
```

**Flujo de procesamiento:**

1. El usuario sube uno o más PDFs y selecciona el tipo de documento.
2. `utils.extraer_texto_pdf` intenta extraer texto plano con `pdfplumber`.
3. Si el texto extraído es insuficiente (PDF escaneado), `utils.convertir_pdf_a_imagenes_base64` renderiza las páginas como imágenes con `pdf2image`.
4. El contenido (texto y/o imágenes) se envía a GPT-4o junto con un `json_schema` estricto generado desde el modelo Pydantic correspondiente.
5. La respuesta se valida nuevamente contra el esquema Pydantic como capa de seguridad adicional.
6. El resultado se muestra en la UI y queda disponible para descarga.

---

## 📂 Estructura del repositorio

```
docuextract-api/
├── app.py              # Aplicación principal Streamlit (UI)
├── utils.py             # Lógica de extracción de PDF + cliente OpenAI + esquemas Pydantic
├── requirements.txt      # Dependencias de Python
├── packages.txt          # Dependencias de sistema (poppler, requerido por pdf2image)
├── .env.example           # Plantilla de variables de entorno
├── .gitignore
└── README.md
```

---

## 🚀 Instalación local

### 1. Requisitos previos

- Python 3.10 o superior
- [`poppler`](https://poppler.freedesktop.org/) instalado en el sistema (requerido por `pdf2image`):
  - **macOS:** `brew install poppler`
  - **Ubuntu/Debian:** `sudo apt-get install poppler-utils`
  - **Windows:** descargar los binarios de poppler y agregarlos al `PATH`.

### 2. Clonar el repositorio

```bash
git clone https://github.com/tu-usuario/docuextract-api.git
cd docuextract-api
```

### 3. Crear entorno virtual e instalar dependencias

```bash
python -m venv venv
source venv/bin/activate   # En Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 4. Configurar variables de entorno

```bash
cp .env.example .env
# Editar .env y completar OPENAI_API_KEY=sk-...
```

### 5. Ejecutar la aplicación

```bash
streamlit run app.py
```

La aplicación quedará disponible en `http://localhost:8501`.

---

## ☁️ Despliegue en Streamlit Community Cloud

1. Subí este repositorio a GitHub (asegurate de que `.env` **no** esté incluido — ya está en `.gitignore`).
2. Entrá a [share.streamlit.io](https://share.streamlit.io) y creá una nueva app apuntando a tu repositorio y a `app.py`.
3. En **Settings → Secrets**, agregá:
   ```toml
   OPENAI_API_KEY = "sk-tu-clave-real"
   ```
4. Streamlit Cloud instalará automáticamente las dependencias de `requirements.txt` y los paquetes de sistema listados en `packages.txt` (incluye `poppler-utils`, necesario para procesar PDFs escaneados).
5. ¡Listo! La app quedará disponible en una URL pública tipo `https://tu-app.streamlit.app`.

> 💡 Si preferís no usar Secrets, cualquier usuario puede ingresar su propia API Key directamente en la barra lateral de la app en tiempo de ejecución.

---

## 🔐 Manejo de errores

La aplicación contempla de forma explícita los siguientes escenarios:

| Escenario | Comportamiento |
|---|---|
| PDF corrupto o protegido con contraseña | Se informa el error puntual y se continúa con el resto de los archivos |
| API Key inválida o sin permisos | Se detiene el procesamiento por lotes y se muestra un mensaje claro |
| Límite de solicitudes (rate limit) excedido | Se detiene el procesamiento y se sugiere reintentar más tarde |
| Respuesta de OpenAI que no cumple el esquema | Se informa el error y se continúa con el resto de los archivos |
| Errores de conexión con OpenAI | Se captura y se muestra un mensaje amigable, sin romper la app |

---

## 🗺️ Esquemas de extracción soportados

| Tipo de documento | Campos destacados |
|---|---|
| **Factura** | número, fechas, emisor/receptor, ítems, subtotal, impuestos, total |
| **Contrato** | partes involucradas, objeto, duración, monto, cláusulas clave, jurisdicción |
| **Escritura** | escribano, otorgante/adquirente, inmueble, matrícula catastral, gravámenes |
| **Genérico** | título, fecha, entidades mencionadas, resumen, pares clave-valor |

---

## 🛣️ Roadmap sugerido

- [ ] Exponer la lógica de `utils.py` como endpoints REST con FastAPI (modo API pura, sin UI).
- [ ] Persistencia de resultados en base de datos (PostgreSQL / Supabase).
- [ ] Autenticación multi-usuario y multi-tenant.
- [ ] Panel de métricas de uso y costos de la API de OpenAI.

---

## 📜 Licencia

MIT — libre para uso comercial y modificación.

---

Desarrollado por **Mario Data Tech**.
