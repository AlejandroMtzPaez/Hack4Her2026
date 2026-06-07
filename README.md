# Always on Shelf

> **Agente de IA que aprende cualquier proceso web por observación y lo replica de forma autónoma — sin reglas escritas a mano.**

Desarrollado para el reto **Always on Shelf** de **Arca Continental**, este agente resuelve el problema de captura manual de órdenes de compra en el canal moderno: en lugar de que un operativo copie datos entre dos portales, el agente observa el flujo una sola vez, aprende el procedimiento con IA, y lo ejecuta automáticamente en todos los registros siguientes.

---

## El problema

Las grandes cadenas del canal moderno (Walmart, Soriana, Chedraui, OXXO, Sam's Club) emiten órdenes de compra a través de sus propios portales web. Cuando no existe un EDI activo, alguien tiene que entrar manualmente al portal del cliente, leer la orden, y capturarla en el sistema interno de Arca Continental.

Este flujo tiene tres fallas estructurales:

- **No escala** — a mayor volumen de clientes, más personas haciendo lo mismo.
- **Es propenso a errores** — captura manual en formatos distintos por cada cliente.
- **No tiene alternativa viable a corto plazo** — implementar EDI toma meses por cliente.

---

## La solución

Un motor de IA que opera en tres fases sobre **cualquier** par de sistemas web:

```
👁 OBSERVAR          🧠 GENERALIZAR          ⚡ REPLICAR
El usuario hace     Gemini convierte la     El agente ejecuta
el proceso UNA      demostración en una     el procedimiento
sola vez.           receta reutilizable.    en todos los datos.
```

Lo que diferencia este agente:

- **Sin reglas hardcodeadas.** El mapeo entre sistemas lo infiere Gemini comparando valores y semántica en tiempo real.
- **Funciona en cualquier interfaz.** El extractor genérico maneja documentos, tablas, tarjetas CRM, tickets, fichas de producto.
- **Escalabilidad demostrable.** 1 demostración → N ejecuciones automáticas.
- **Razonamiento real.** El Caso Supremo permite dar un objetivo en lenguaje natural ("compra los 2 más baratos") y el agente lo cumple sin instrucciones previas.

---

## Demo rápido

```bash
# Instalar
pip install -r requirements.txt
python -m playwright install chromium

# Configurar
# → pegar GEMINI_API_KEY en agente_universal.py y caso_supremo.py

# Lanzar el dashboard web (todo desde el navegador, sin terminal)
python web.py
# → abrir http://localhost:8500
```

O desde terminal:

```bash
# Enseñar el proceso una vez
python agente_universal.py grabar ordenes

# Ejecutar en todos los registros (escalabilidad)
python agente_universal.py lote ordenes

# Caso supremo: razonamiento con objetivo en lenguaje natural
python caso_supremo.py "compra los 2 productos mas baratos"

# Caso supremo: observar y replicar sesión de compras
python caso_supremo.py grabar
python caso_supremo.py replicar
```

---

## Capacidades

### 1. Motor genérico de aprendizaje (`agente_universal.py`)

Cinco procesos de negocio reales, cada uno sobre sistemas con **estructura HTML genuinamente distinta**, demostrando que el agente aprende sin importar la interfaz:

| Proceso | Sistema origen | Estructura | Sistema destino | Transformaciones |
|---|---|---|---|---|
| `ordenes` | Portal GCP | Documento `dl/dt/dd` | ERP por secciones | Copia + renombrado |
| `facturacion` | FacturaPro | Grid contable oscuro | CFDI oficial | Fecha, número limpio, RFC mayúsculas |
| `alta_catalogo` | ProveedorLink | Ficha e-commerce (spec grid) | Dashboard oscuro | Precio limpio, marca mayúsculas |
| `catalogo_clientes` | ClienteNet | Tarjeta CRM con avatar | CRM sectioned | Conversión de identificador (nombre → clave) |
| `compra_sitio` | ReqFast | Ticket de requisición | Checkout e-commerce | Selección + clic (acciones, no solo datos) |

**Comandos:**

```bash
python agente_universal.py grabar <proceso>              # aprende una vez
python agente_universal.py reproducir <proceso> <id>     # ejecuta en un registro
python agente_universal.py lote <proceso>                # ejecuta en todos
python agente_universal.py lote <proceso> ID1 ID2 ID3    # ejecuta en los indicados
python agente_universal.py skills                        # muestra lo aprendido
python agente_universal.py limpiar [proceso]             # resetea memoria
```

El flujo `lote` imprime al terminar:

```
=== RESUMEN DE ESCALABILIDAD ===
   4/4 registros procesados correctamente
   Tiempo total: 4.0 s  (1.0 s por registro)
   1 demostración humana → 4 ejecuciones automáticas
```

---

### 2. Caso Supremo (`caso_supremo.py`)

Dos modos que demuestran capacidades distintas sobre **saucedemo.com** (sitio externo real):

#### Modo 1 — Razonamiento con Gemini

El agente lee el catálogo en vivo, llama a Gemini con el objetivo, y compra lo que decide. El catálogo se lee en tiempo real: el agente no sabe los precios de antemano.

```bash
python caso_supremo.py "compra los 2 productos mas baratos"
python caso_supremo.py "compra todo lo que cueste menos de 15 dolares"
python caso_supremo.py "compra el producto mas caro"
```

El jurado puede proponer el objetivo en vivo. Imposible de hardcodear porque los precios se leen en el momento y Gemini decide.

#### Modo 2 — Observar y replicar

El agente te mira hacer la compra (graba el carrito y el checkout via `localStorage`) y la repite exacta. Sin Gemini, sin hardcoding: pura imitación conductual.

```bash
python caso_supremo.py grabar     # tú compras, el agente graba
python caso_supremo.py replicar   # el agente lo repite solo
```

```bash
# Para probar el flujo sin salida a internet (espejo local de saucedemo):
python caso_supremo.py --local "compra el mas barato"
python caso_supremo.py grabar --local
```

---

### 3. Dashboard web (`web.py`)

Interfaz visual para el demo en vivo, sin necesidad de usar la terminal frente al jurado:

- **Sidebar** con los 5 procesos, badge de estado (aprendido / sin grabar) y fecha.
- **Consola en vivo** con streaming de logs línea a línea via Server-Sent Events.
- **Panel por proceso**: grabar, reproducir, lote, y validación campo por campo animada.
- **Panel Caso Supremo**: tabs para razonamiento y observar/replicar.
- El botón "Terminé de llenar" reemplaza el ENTER de la terminal durante el grabado.

```bash
python web.py
# → http://localhost:8500
```

---

## Cómo funciona por dentro

### Aprendizaje por observación

Durante `grabar`, el motor:

1. Extrae genéricamente los campos del sistema origen (maneja `dl/dt/dd`, tablas, spec grids, tarjetas CRM, tickets de requisición).
2. Inyecta un grabador JavaScript en el sistema destino que captura cada acción del usuario (`[ACCION] campo = valor`).
3. Envía ambos a Gemini con el prompt: *"Para cada acción en el destino, infiere de qué campo del origen vino el valor y qué transformación se aplicó."*
4. Guarda la receta en `skills/<proceso>.json`.

El skill resultante describe el procedimiento por **significado semántico**, no por posición de campos:

```json
{
  "accion": "escribir",
  "origen_etiqueta": "Razón Social Comprador",
  "destino_nombre": "cliente",
  "transform": "copiar",
  "razon": "El campo 'cliente' en el destino corresponde a 'Razón Social Comprador' en el origen por similitud semántica y coincidencia de valor observado."
}
```

Así el mapeo aguanta nombres de campo distintos, layouts diferentes y datos nuevos.

### Transformaciones aprendidas

El agente detecta y aplica transformaciones al comparar el valor del origen con lo que el usuario tecleó:

| Transform | Ejemplo |
|---|---|
| `copiar` | `OC-2024-0001` → `OC-2024-0001` |
| `mayusculas` | `cno950101aaa` → `CNO950101AAA` |
| `numero_limpio` | `$7,800.50` → `7800.50` |
| `fecha:DMY->YMD` | `07/03/2026` → `2026-03-07` |
| `derivar:<regla>` | Conversión arbitraria vía Gemini |

### Reproducción robusta

El reproductor localiza cada campo en capas: primero por selector aprendido, luego por `name`, luego por etiqueta/label. Si el layout cambió ligeramente entre sesiones, el agente encuentra el campo de todas formas.

---

## Arquitectura

```
┌─────────────────────────────────────────────────────┐
│                  Dashboard (web.py)                  │
│         FastAPI + SSE + static/index.html            │
└──────────────┬──────────────┬───────────────────────┘
               │ subprocess   │ subprocess
    ┌──────────▼──────┐  ┌───▼──────────────┐
    │ agente_          │  │ caso_supremo.py  │
    │ universal.py     │  │ · razonamiento   │
    │ · 5 procesos     │  │ · observar       │
    │ · grabar/lote    │  │ · replicar       │
    └──────────┬───────┘  └───────┬──────────┘
               │                  │
    ┌──────────▼──────┐  ┌────────▼──────────┐
    │ Playwright       │  │   Gemini API      │
    │ (browser headed) │  │ (inferencia +     │
    │ Sistema A + B    │  │  razonamiento)    │
    └─────────────────┘  └───────────────────┘
               │
    ┌──────────▼──────┐
    │  skills/*.json  │
    │  (recetas       │
    │   aprendidas)   │
    └─────────────────┘
```

---

## Instalación

**Requisitos:** Python 3.11+, pip

```bash
# Clonar
git clone https://github.com/<tu-usuario>/always-on-shelf.git
cd always-on-shelf

# Entorno virtual (recomendado)
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate

# Dependencias
pip install -r requirements.txt
python -m playwright install chromium

# Dashboard web (dependencias adicionales)
pip install fastapi uvicorn sse-starlette aiofiles
```

**API Key de Gemini** (gratis en [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)):

Pégala en los dos archivos:

```python
# agente_universal.py  →  línea ~15
GEMINI_API_KEY = "tu_key_aqui"

# caso_supremo.py  →  línea ~20
GEMINI_API_KEY = "tu_key_aqui"
```

O exportar como variable de entorno:

```bash
# Windows
set GEMINI_API_KEY=tu_key_aqui

# macOS/Linux
export GEMINI_API_KEY=tu_key_aqui
```

---

## Estructura del proyecto

```
always-on-shelf/
│
├── agente_universal.py     # Motor genérico: 5 procesos, grabar/lote/reproducir
├── caso_supremo.py         # Razonamiento + observar/replicar en saucedemo
├── web.py                  # Dashboard FastAPI con streaming SSE
│
├── static/
│   └── index.html          # Frontend del dashboard
│
├── skills/                 # Skills aprendidos (se generan al grabar)
│   ├── ordenes.json
│   ├── facturacion.json
│   ├── alta_catalogo.json
│   ├── catalogo_clientes.json
│   └── compra_sitio.json
│
├── runs/                   # Flags temporales para comunicar web↔agente
├── sesion_grabada.json     # Sesión de compras observada (caso supremo)
│
└── requirements.txt
```

> `skills/` y `sesion_grabada.json` están en `.gitignore` — representan lo aprendido por el agente en cada instalación. Cada instancia aprende desde cero.

---

## Flujo de demo recomendado

### Preparación (antes de presentar)

```bash
# Asegúrate de empezar sin memoria previa
python agente_universal.py limpiar   # escribe "si" para confirmar
python agente_universal.py skills    # debe mostrar "No hay skills grabados"
```

### En vivo frente al jurado

**1. Mostrar el problema (2 min)**
Abre los dos sistemas en el dashboard (portal GCP y ERP interno). Muestra cómo hoy alguien copia datos a mano entre ellos.

**2. Grabar el aprendizaje (3 min)**
Haz clic en "Grabar" en el dashboard. El agente abre los dos navegadores. Llena el formulario interno una vez con los datos de la orden. Haz clic en "Terminé". En la consola aparece el mapeo aprendido campo por campo con la razón de Gemini.

**3. Escalabilidad (3 min)**
Haz clic en "Ejecutar en 4 registros". El agente procesa las 4 órdenes solo. La consola muestra los logs en tiempo real. Al terminar: *"1 demostración → 4 ejecuciones automáticas, 4/4 correctas"*.

**4. Caso Supremo — razonamiento (3 min)**
Pídele al jurado que proponga un objetivo: "¿qué quieren que compre el agente?" Escríbelo en el dashboard. El agente entra a saucedemo, lee los 6 productos con precios actuales, Gemini decide, y ejecuta la compra.

**5. Caso Supremo — observar y replicar (2 min)**
Haz la compra tú normalmente en saucedemo (el agente te observa). Luego haz clic en "Replicar" — el agente repite exactamente la misma sesión sin que toques nada.

### Respuesta a "¿cómo sé que no está hardcodeado?"

- Ejecuta con un registro que el agente nunca vio (cambia el ID en el dashboard).
- Abre `skills/ordenes.json` y muestra la razón semántica que infirió Gemini para cada mapeo.
- Cambia el objetivo del Caso Supremo en vivo: si el resultado cambia, no puede estar hardcodeado.

---

## Stack tecnológico

| Capa | Tecnología |
|---|---|
| Automatización web | [Playwright](https://playwright.dev/python/) |
| IA / Inferencia | [Google Gemini API](https://aistudio.google.com) (`gemini-2.5-flash`) |
| Backend dashboard | [FastAPI](https://fastapi.tiangolo.com/) + SSE |
| Frontend dashboard | HTML / CSS / JS (sin build step) |
| Sistemas de demo | Servidores HTTP en memoria (Python `http.server`) |
| Sitio externo real | [saucedemo.com](https://www.saucedemo.com) |

---

## Contexto del reto

**Always on Shelf** — Arca Continental Hackathon  
**Problema:** automatizar la captura de órdenes de compra del canal moderno sin EDI.  
**Enfoque elegido:** un agente universal que aprende por observación, generalizable a cualquier flujo web.

El reto evalúa: aprendizaje por observación · reproducción autónoma · exactitud · replicabilidad.

---

## Licencia

MIT — libre para usar, modificar y distribuir con atribución.
