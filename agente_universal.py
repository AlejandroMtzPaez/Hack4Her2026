"""
AGENTE UNIVERSAL — Always on Shelf
===================================
Un solo motor que APRENDE cualquier proceso web por observacion y lo REPRODUCE
con datos nuevos. No tiene reglas por tarea: graba una demostracion como una
"receta" (skill) reutilizable y la ejecuta.

Cubre formularios, registro de ordenes, facturacion y conversion de
identificadores con EL MISMO codigo. Cada proceso aprendido se guarda como un
skill en la carpeta skills/.

------------------------------------------------------------------------------
USO (una sola ventana de PowerShell, en la carpeta de este archivo):

    python agente_universal.py grabar ordenes
        Abre el proceso, TU lo haces UNA vez, Gemini aprende la receta.

    python agente_universal.py reproducir ordenes OC-2024-0003
        El agente ejecuta la receta solo, con datos que nunca vio, y valida.

    python agente_universal.py grabar facturacion
    python agente_universal.py reproducir facturacion CLI-03

    python agente_universal.py skills        # lista lo aprendido
    python agente_universal.py prueba        # verifica TODO sin gastar tokens

------------------------------------------------------------------------------
ANTES DE CORRER:
    pip install playwright google-genai python-dotenv
    python -m playwright install chromium
    API key gratis: https://aistudio.google.com/app/apikey  -> pegala abajo.
"""
import os
import re
import sys
import json
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ====== CONFIG ======
GEMINI_API_KEY = ""  # <-- key (o usa variable de entorno)
GEMINI_MODELO = "gemini-2.5-flash"  # estable y en free tier; o "gemini-3.5-flash"
CARPETA_SKILLS = "skills"

# Procesos de demo. Esto es CONFIGURACION (solo URLs), no logica por tarea:
# el motor es el mismo para cualquier par de URLs.
PROCESOS = {
    "ordenes": {
        "titulo": "Registro de ordenes de compra",
        "origen_url_template": "http://localhost:8000/oc.html?id={registro}",
        "destino_url": "http://localhost:8001/orden.html",
        "demo": "OC-2024-0001", "reproduce": "OC-2024-0003",
        "registros": ["OC-2024-0001", "OC-2024-0002", "OC-2024-0003", "OC-2024-0004"],
    },
    "facturacion": {
        "titulo": "Facturacion con conversion de identificadores",
        "origen_url_template": "http://localhost:8000/cliente.html?id={registro}",
        "destino_url": "http://localhost:8001/factura.html",
        "demo": "CLI-01", "reproduce": "CLI-03",
        "registros": ["CLI-01", "CLI-02", "CLI-03", "CLI-04"],
    },
    "alta_catalogo": {
        "titulo": "Alta de productos en catalogo",
        "origen_url_template": "http://localhost:8000/producto.html?id={registro}",
        "destino_url": "http://localhost:8001/catalogo.html",
        "demo": "ART-1001", "reproduce": "ART-1003",
        "registros": ["ART-1001", "ART-1002", "ART-1003", "ART-1004"],
    },
    "catalogo_clientes": {
        "titulo": "Conversion de catalogo de clientes (identificadores)",
        "origen_url_template": "http://localhost:8000/clientes_dir.html?id={registro}",
        "destino_url": "http://localhost:8001/crm.html",
        "demo": "DIR-01", "reproduce": "DIR-03",
        "registros": ["DIR-01", "DIR-02", "DIR-03", "DIR-04"],
    },
    "compra_sitio": {
        "titulo": "Identificar y replicar acciones de compra",
        "origen_url_template": "http://localhost:8000/lista_compra.html?id={registro}",
        "destino_url": "http://localhost:8001/tienda.html",
        "demo": "LC-01", "reproduce": "LC-03",
        "registros": ["LC-01", "LC-02", "LC-03", "LC-04"],
    },
}
# ====================


# ==================== HTML EMBEBIDO (estructuras genuinamente distintas) ====================
# Cada sistema origen usa una estructura HTML diferente:
# 1. OC:    dl/dt/dd (documento de compra)
# 2. CLI:   table (grid contable oscuro)
# 3. ART:   spec-k/spec-v (ficha de producto e-commerce)
# 4. DIR:   pfl/pfv (tarjeta de perfil CRM)
# 5. LC:    req-k/req-v (ticket de requisicion)

PORTALES_ROOT = "<!DOCTYPE html><html lang='es'><head><meta charset='UTF-8'><title>Portales externos</title><style>*{box-sizing:border-box;margin:0;padding:0}body{font-family:'Segoe UI',Arial,sans-serif;background:#f8fafc}header{background:#0f2740;color:#fff;padding:14px 28px}header h1{font-size:15px;font-weight:600}.wrap{max-width:660px;margin:28px auto;padding:0 18px}.title{font-size:13px;font-weight:700;color:#374151;margin-bottom:14px}.links{display:flex;flex-direction:column;gap:10px}.link-card{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:14px 18px;text-decoration:none;color:#1f2937;display:flex;align-items:center;gap:12px}.link-card:hover{border-color:#2563eb;background:#eff6ff}.link-icon{font-size:22px;width:36px;text-align:center}.link-txt .name{font-weight:600;font-size:14px}.link-txt .sub{font-size:11px;color:#9ca3af;margin-top:2px}</style></head><body><header><h1>Portales de clientes (sistemas externos)</h1></header><div class='wrap'><div class='title'>Selecciona el proceso a demostrar</div><div class='links'><a class='link-card' href='oc.html?id=OC-2024-0001'><span class='link-icon'>&#128196;</span><div class='link-txt'><div class='name'>Portal GCP &mdash; Ordenes de compra</div><div class='sub'>Estructura: documento con dl/dt/dd</div></div></a><a class='link-card' href='cliente.html?id=CLI-01'><span class='link-icon'>&#128202;</span><div class='link-txt'><div class='name'>FacturaPro &mdash; Datos de facturacion</div><div class='sub'>Estructura: tabla estilo grid contable</div></div></a><a class='link-card' href='producto.html?id=ART-1001'><span class='link-icon'>&#128230;</span><div class='link-txt'><div class='name'>ProveedorLink &mdash; Ficha de producto</div><div class='sub'>Estructura: pagina de producto e-commerce</div></div></a><a class='link-card' href='clientes_dir.html?id=DIR-01'><span class='link-icon'>&#128101;</span><div class='link-txt'><div class='name'>ClienteNet &mdash; Perfil de cliente</div><div class='sub'>Estructura: tarjeta CRM con campos inline</div></div></a><a class='link-card' href='lista_compra.html?id=LC-01'><span class='link-icon'>&#128203;</span><div class='link-txt'><div class='name'>ReqFast &mdash; Requisicion de compra</div><div class='sub'>Estructura: ticket de solicitud</div></div></a></div></div></body></html>"

INTERNOS_ROOT = "<!DOCTYPE html><html lang='es'><head><meta charset='UTF-8'><title>Sistemas internos</title><style>*{box-sizing:border-box;margin:0;padding:0}body{font-family:'Segoe UI',Arial,sans-serif;background:#f8fafc}header{background:#1e293b;color:#fff;padding:14px 28px}header h1{font-size:15px;font-weight:600}.wrap{max-width:660px;margin:28px auto;padding:0 18px}.title{font-size:13px;font-weight:700;color:#374151;margin-bottom:14px}.links{display:flex;flex-direction:column;gap:10px}.link-card{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:14px 18px;text-decoration:none;color:#1f2937;display:flex;align-items:center;gap:12px}.link-card:hover{border-color:#2563eb;background:#eff6ff}.link-icon{font-size:22px;width:36px;text-align:center}.link-txt .name{font-weight:600;font-size:14px}.link-txt .sub{font-size:11px;color:#9ca3af;margin-top:2px}</style></head><body><header><h1>Sistemas internos de Arca Continental</h1></header><div class='wrap'><div class='title'>Sistemas destino</div><div class='links'><a class='link-card' href='orden.html'><span class='link-icon'>&#128203;</span><div class='link-txt'><div class='name'>SistemaAC &mdash; Captura de ordenes</div><div class='sub'>Formulario ERP por secciones</div></div></a><a class='link-card' href='factura.html'><span class='link-icon'>&#128195;</span><div class='link-txt'><div class='name'>SistemaAC &mdash; Emision CFDI</div><div class='sub'>Formulario estilo documento oficial</div></div></a><a class='link-card' href='catalogo.html'><span class='link-icon'>&#128736;</span><div class='link-txt'><div class='name'>SistemaAC &mdash; Catalogo de articulos</div><div class='sub'>Panel oscuro estilo dashboard</div></div></a><a class='link-card' href='crm.html'><span class='link-icon'>&#128101;</span><div class='link-txt'><div class='name'>SistemaAC &mdash; CRM de clientes</div><div class='sub'>Formulario CRM con secciones</div></div></a><a class='link-card' href='tienda.html'><span class='link-icon'>&#128722;</span><div class='link-txt'><div class='name'>SistemaAC &mdash; Compra en tienda</div><div class='sub'>Checkout estilo e-commerce</div></div></a></div></div></body></html>"

OC_HTML = '<!DOCTYPE html><html lang=\'es\'><head><meta charset=\'UTF-8\'><title>Orden de Compra - Portal GCP</title><style>*{box-sizing:border-box;margin:0;padding:0}body{font-family:\'Segoe UI\',Arial,sans-serif;background:#edf2f7}header{background:#0f2740;color:#fff;padding:14px 28px;display:flex;align-items:center;gap:16px}header h1{font-size:16px;font-weight:600}header .badge{background:#2a4a6e;color:#90cdf4;padding:3px 10px;border-radius:4px;font-size:11px;font-weight:700}.wrap{max-width:820px;margin:24px auto;padding:0 18px}.po-doc{background:#fff;border:1px solid #cbd5e0;border-radius:6px;overflow:hidden}.po-banner{background:#0f2740;color:#fff;padding:18px 28px;display:flex;justify-content:space-between;align-items:center}.po-banner .title{font-size:18px;font-weight:700;letter-spacing:2px;text-transform:uppercase}.po-banner .folio-box{background:#1a3a5c;padding:8px 16px;border-radius:4px;font-family:monospace;font-size:22px;font-weight:700;color:#90cdf4}.po-body{padding:0}.po-section{padding:16px 28px;border-bottom:1px solid #e2e8f0}.po-section:last-child{border-bottom:none}.section-lbl{font-size:10px;font-weight:700;color:#4a5568;letter-spacing:1.5px;text-transform:uppercase;margin-bottom:10px}dl{display:grid;grid-template-columns:repeat(2,1fr);gap:0}dl.single{grid-template-columns:1fr}dl.triple{grid-template-columns:repeat(3,1fr)}dt{font-size:11px;color:#718096;padding:5px 0 2px}dd{font-size:14px;font-weight:600;color:#1a202c;padding:0 16px 10px 0;border-bottom:1px dotted #e2e8f0;margin:0}.amount dd{font-size:16px;color:#0f2740}</style></head><body><header><h1>Portal GCP</h1><span class=\'badge\'>PROVEEDOR</span></header><div class=\'wrap\'><div class=\'po-doc\'><div class=\'po-banner\'><span class=\'title\'>Orden de Compra</span><span class=\'folio-box\' id=\'folio\'></span></div><div class=\'po-body\'><div class=\'po-section\'><div class=\'section-lbl\'>Comprador</div><dl class=\'single\'><dt>Razon Social Comprador</dt><dd id=\'razon\'></dd></dl></div><div class=\'po-section\'><div class=\'section-lbl\'>Logistica</div><dl><dt>Fecha Emision</dt><dd id=\'emision\'></dd><dt>Fecha Requerida</dt><dd id=\'requerida\'></dd></dl><dl class=\'single\'><dt>Centro de Distribucion</dt><dd id=\'cedis\'></dd></dl></div><div class=\'po-section\'><div class=\'section-lbl\'>Condiciones</div><dl><dt>Condiciones de Pago</dt><dd id=\'pago\'></dd><dt>Moneda</dt><dd id=\'moneda\'></dd></dl></div><div class=\'po-section amount\'><div class=\'section-lbl\'>Importes</div><dl class=\'triple\'><dt>Subtotal</dt><dd id=\'subtotal\'></dd><dt>IVA (16%)</dt><dd id=\'iva\'></dd><dt>Total</dt><dd id=\'total\'></dd></dl></div></div></div></div><script>var DATOS={"OC-2024-0001": {"folio": "OC-2024-0001", "razon": "Grupo Comercial del Pacifico", "emision": "03/03/2026", "requerida": "10/03/2026", "cedis": "CEDIS Guadalajara", "pago": "30 dias", "moneda": "MXN", "subtotal": "100000.00", "iva": "16000.00", "total": "116000.00"}, "OC-2024-0002": {"folio": "OC-2024-0002", "razon": "Autoservicios Reyes del Bajio", "emision": "05/03/2026", "requerida": "14/03/2026", "cedis": "CEDIS Monterrey", "pago": "45 dias", "moneda": "MXN", "subtotal": "250000.00", "iva": "40000.00", "total": "290000.00"}, "OC-2024-0003": {"folio": "OC-2024-0003", "razon": "Tiendas del Sureste SA de CV", "emision": "07/03/2026", "requerida": "21/03/2026", "cedis": "CEDIS Merida", "pago": "60 dias", "moneda": "USD", "subtotal": "18000.00", "iva": "2880.00", "total": "20880.00"}, "OC-2024-0004": {"folio": "OC-2024-0004", "razon": "Comercializadora del Golfo", "emision": "09/03/2026", "requerida": "16/03/2026", "cedis": "CEDIS Veracruz", "pago": "15 dias", "moneda": "MXN", "subtotal": "75000.00", "iva": "12000.00", "total": "87000.00"}};var id=new URLSearchParams(location.search).get(\'id\')||\'OC-2024-0001\';var d=DATOS[id]||DATOS[\'OC-2024-0001\'];["folio", "razon", "emision", "requerida", "cedis", "pago", "moneda", "subtotal", "iva", "total"].forEach(function(k){document.getElementById(k).textContent=d[k];});document.body.setAttribute(\'data-cargado\',\'true\');</script></body></html>'

CLIENTE_HTML = '<!DOCTYPE html><html lang=\'es\'><head><meta charset=\'UTF-8\'><title>FacturaPro - Datos de Facturacion</title><style>*{box-sizing:border-box;margin:0;padding:0}body{font-family:\'Segoe UI\',Arial,sans-serif;background:#0d1117;min-height:100vh}header{background:linear-gradient(135deg,#161b22,#21262d);color:#e6edf3;padding:14px 28px;border-bottom:1px solid #30363d;display:flex;align-items:center;justify-content:space-between}header h1{font-size:15px;font-weight:600}.hbadge{background:#388bfd22;color:#388bfd;border:1px solid #388bfd55;padding:3px 10px;border-radius:12px;font-size:11px}.wrap{max-width:900px;margin:24px auto;padding:0 18px}.toolbar{background:#161b22;border:1px solid #30363d;border-radius:8px 8px 0 0;padding:10px 16px;display:flex;gap:12px;align-items:center}.mock-search{background:#0d1117;border:1px solid #30363d;color:#8b949e;padding:6px 12px;border-radius:6px;font-size:12px;width:220px}.rec-count{color:#484f58;font-size:11px;margin-left:auto}.grid-wrap{border:1px solid #30363d;border-top:none;border-radius:0 0 8px 8px;overflow:auto}table{width:100%;border-collapse:collapse;font-size:13px}thead{background:#161b22}th{color:#388bfd;padding:11px 14px;text-align:left;font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid #30363d}tbody tr{background:#0d1117}tbody tr:nth-child(even){background:#161b22}td{padding:12px 14px;color:#e6edf3;border-bottom:1px solid #21262d;font-weight:500}</style></head><body><header><h1>FacturaPro</h1><span class=\'hbadge\'>Sistema de Facturacion</span></header><div class=\'wrap\'><div class=\'toolbar\'><input class=\'mock-search\' placeholder=\'Buscar cliente...\' readonly><span class=\'rec-count\'>1 registro</span></div><div class=\'grid-wrap\'><table><thead><tr><th>Razon Social</th><th>RFC</th><th>Fecha factura</th><th>Subtotal</th><th>Metodo de pago</th></tr></thead><tbody><tr id=\'fila\'></tr></tbody></table></div></div><script>var DATOS={"CLI-01": {"razon": "Comercializadora del Norte SA de CV", "rfc": "cno950101aaa", "fecha": "07/03/2026", "subtotal": "$18,000.00", "metodo": "Transferencia"}, "CLI-02": {"razon": "Distribuidora Bajio SA", "rfc": "dba880515h22", "fecha": "12/04/2026", "subtotal": "$45,250.00", "metodo": "Credito"}, "CLI-03": {"razon": "Abarrotes del Centro", "rfc": "acc010203xy9", "fecha": "01/05/2026", "subtotal": "$7,800.50", "metodo": "Contado"}, "CLI-04": {"razon": "Mayoreo Peninsular SA", "rfc": "mpe991231qq0", "fecha": "23/05/2026", "subtotal": "$132,000.00", "metodo": "Transferencia"}};var id=new URLSearchParams(location.search).get(\'id\')||\'CLI-01\';var d=DATOS[id]||DATOS[\'CLI-01\'];[].forEach(function(k){document.getElementById(k).textContent=d[k];});var ks=[\'razon\',\'rfc\',\'fecha\',\'subtotal\',\'metodo\'];document.getElementById(\'fila\').innerHTML=ks.map(function(k){return \'<td>\'+d[k]+\'</td>\';}).join(\'\');document.body.setAttribute(\'data-cargado\',\'true\');</script></body></html>'

ORDEN_HTML = '<!DOCTYPE html><html lang=\'es\'><head><meta charset=\'UTF-8\'><title>SistemaAC - Captura de Ordenes</title><style>*{box-sizing:border-box;margin:0;padding:0}body{font-family:\'Segoe UI\',Arial,sans-serif;background:#f1f5f9}header{background:#1e293b;color:#e2e8f0;padding:13px 28px;border-bottom:3px solid #2563eb}header h1{font-size:15px;font-weight:600}.wrap{max-width:700px;margin:24px auto;padding:0 18px}.form-card{background:#fff;border:1px solid #e2e8f0;border-radius:8px;overflow:hidden}.form-sec{padding:18px 24px;border-bottom:1px solid #f1f5f9}.form-sec:last-child{border-bottom:none}.sec-hd{font-size:10px;font-weight:700;color:#2563eb;text-transform:uppercase;letter-spacing:.8px;margin-bottom:12px;padding-bottom:6px;border-bottom:2px solid #dbeafe}.form-row{margin-bottom:11px}.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:11px}label{display:block;font-size:10px;color:#64748b;margin-bottom:4px;font-weight:700;text-transform:uppercase;letter-spacing:.3px}input,select{width:100%;padding:8px 10px;font-size:13px;border:1px solid #e2e8f0;border-radius:6px;background:#f8fafc;color:#0f172a}input:focus,select:focus{outline:none;border-color:#2563eb;background:#fff}button{margin-top:4px;background:#2563eb;color:#fff;border:none;padding:10px 22px;font-size:13px;border-radius:6px;cursor:pointer;font-weight:700}#confirmacion{margin-top:14px;background:#f0fdf4;border:1px solid #bbf7d0;border-radius:6px;padding:14px;display:none}#confirmacion h3{font-size:12px;color:#166534;margin:0 0 8px}.cf{display:flex;padding:4px 0;font-size:12px;border-bottom:1px solid #dcfce7}.cf:last-child{border-bottom:none}.cn{flex:0 0 45%;color:#6b7280}.cv{flex:1;font-weight:600;color:#0f172a}</style></head><body><header><h1>SistemaAC &mdash; Captura de Ordenes de Compra</h1></header><div class=\'wrap\'><div class=\'form-card\'><div class=\'form-sec\'><div class=\'sec-hd\'>Identificacion</div><div class=\'form-row\'><label for=\'f_numero_orden\'>Numero de orden</label><input id=\'f_numero_orden\' name=\'numero_orden\' autocomplete=\'off\'></div><div class=\'form-row\'><label for=\'f_cliente\'>Cliente</label><input id=\'f_cliente\' name=\'cliente\' autocomplete=\'off\'></div></div><div class=\'form-sec\'><div class=\'sec-hd\'>Logistica</div><div class=\'form-grid\'><div class=\'form-row\'><label for=\'f_fecha_pedido\'>Fecha pedido</label><input id=\'f_fecha_pedido\' name=\'fecha_pedido\' autocomplete=\'off\'></div><div class=\'form-row\'><label for=\'f_fecha_entrega\'>Fecha entrega</label><input id=\'f_fecha_entrega\' name=\'fecha_entrega\' autocomplete=\'off\'></div></div><div class=\'form-row\'><label for=\'f_destino_envio\'>Destino de envio</label><input id=\'f_destino_envio\' name=\'destino_envio\' autocomplete=\'off\'></div></div><div class=\'form-sec\'><div class=\'sec-hd\'>Condiciones y montos</div><div class=\'form-grid\'><div class=\'form-row\'><label for=\'f_terminos_pago\'>Terminos de pago</label><select id=\'f_terminos_pago\' name=\'terminos_pago\'><option value=\'\'>-</option><option>Contado</option><option>15 dias</option><option>30 dias</option><option>45 dias</option><option>60 dias</option></select></div><div class=\'form-row\'><label for=\'f_divisa\'>Divisa</label><select id=\'f_divisa\' name=\'divisa\'><option value=\'\'>-</option><option>MXN</option><option>USD</option><option>EUR</option></select></div></div><div class=\'form-grid\'><div class=\'form-row\'><label for=\'f_importe_neto\'>Importe neto</label><input id=\'f_importe_neto\' name=\'importe_neto\' autocomplete=\'off\'></div><div class=\'form-row\'><label for=\'f_impuesto\'>Impuesto</label><input id=\'f_impuesto\' name=\'impuesto\' autocomplete=\'off\'></div></div><div class=\'form-row\'><label for=\'f_monto_total\'>Monto total</label><input id=\'f_monto_total\' name=\'monto_total\' autocomplete=\'off\'></div><button id=\'btn_guardar\' onclick=\'guardar()\'>Registrar orden</button><div id=\'confirmacion\'><h3>Orden registrada</h3><div id=\'cf\'></div></div></div></div></div><script>function agregar(){var e=document.getElementById(\'estado\');if(e){e.textContent=\'En carrito: \'+(document.getElementById(\'f_producto\').value||\'\')+\' x \'+(document.getElementById(\'f_cantidad\').value||\'\');}}function guardar(){var c=document.getElementById(\'cf\');c.innerHTML=\'\';document.querySelectorAll(\'input,select\').forEach(function(el){var f=document.createElement(\'div\');f.className=\'cf\';f.innerHTML=\'<span class="cn">\'+el.name+\'</span><span class="cv" data-campo="\'+el.name+\'">\'+(el.value||\'-\')+\'</span>\';c.appendChild(f);});document.getElementById(\'confirmacion\').style.display=\'block\';document.body.setAttribute(\'data-guardado\',\'true\');}</script></body></html>'

FACTURA_HTML = '<!DOCTYPE html><html lang=\'es\'><head><meta charset=\'UTF-8\'><title>SistemaAC - Facturacion CFDI</title><style>*{box-sizing:border-box;margin:0;padding:0}body{font-family:\'Segoe UI\',Arial,sans-serif;background:#f8f9fa}header{background:#14532d;color:#fff;padding:13px 28px}header h1{font-size:15px;font-weight:600}.wrap{max-width:700px;margin:24px auto;padding:0 18px}.doc-card{background:#fff;border:1px solid #d1fae5;border-radius:4px;overflow:hidden}.doc-top{background:#14532d;color:#fff;padding:14px 24px;display:flex;justify-content:space-between;align-items:center}.doc-top .ttl{font-size:12px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase}.doc-top .serie{font-family:monospace;background:#1a6335;padding:4px 12px;border-radius:4px;font-size:13px}.doc-sec{padding:16px 24px;border-bottom:1px solid #d1fae5}.doc-sec:last-child{border-bottom:none}.doc-lbl{font-size:10px;font-weight:700;color:#065f46;letter-spacing:1px;text-transform:uppercase;margin-bottom:10px}.stamp-area{background:#f0fdf4;border:1px dashed #86efac;border-radius:4px;padding:8px;text-align:center;color:#9ca3af;font-size:10px;margin-bottom:10px}.form-row{margin-bottom:10px}.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}label{display:block;font-size:10px;color:#065f46;margin-bottom:3px;font-weight:700}input,select{width:100%;padding:8px 10px;font-size:13px;border:1px solid #d1fae5;border-radius:4px;background:#f0fdf4;color:#0f172a}input:focus,select:focus{outline:none;border-color:#059669}button{margin-top:4px;background:#059669;color:#fff;border:none;padding:10px 22px;font-size:13px;border-radius:4px;cursor:pointer;font-weight:700}#confirmacion{margin-top:14px;background:#f0fdf4;border:1px solid #86efac;border-radius:4px;padding:14px;display:none}#confirmacion h3{font-size:12px;color:#065f46;margin:0 0 8px}.cf{display:flex;padding:4px 0;font-size:12px;border-bottom:1px dashed #d1fae5}.cf:last-child{border-bottom:none}.cn{flex:0 0 45%;color:#6b7280}.cv{flex:1;font-weight:600;color:#0f172a}</style></head><body><header><h1>SistemaAC &mdash; Emision de CFDI</h1></header><div class=\'wrap\'><div class=\'doc-card\'><div class=\'doc-top\'><span class=\'ttl\'>Comprobante Fiscal Digital</span><span class=\'serie\'>CFDI 4.0</span></div><div class=\'doc-sec\'><div class=\'stamp-area\'>&#128396; Timbre SAT pendiente</div><div class=\'doc-lbl\'>Datos del Receptor</div><div class=\'form-row\'><label for=\'f_rfc\'>RFC receptor</label><input id=\'f_rfc\' name=\'rfc_receptor\' autocomplete=\'off\'></div><div class=\'form-row\'><label for=\'f_razon\'>Razon social receptor</label><input id=\'f_razon\' name=\'razon_receptor\' autocomplete=\'off\'></div></div><div class=\'doc-sec\'><div class=\'doc-lbl\'>Concepto</div><div class=\'form-grid\'><div class=\'form-row\'><label for=\'f_fecha\'>Fecha CFDI (AAAA-MM-DD)</label><input id=\'f_fecha\' name=\'fecha_cfdi\' autocomplete=\'off\'></div><div class=\'form-row\'><label for=\'f_importe\'>Importe</label><input id=\'f_importe\' name=\'importe\' autocomplete=\'off\'></div></div><div class=\'form-row\'><label for=\'f_forma\'>Forma de pago</label><select id=\'f_forma\' name=\'forma_pago\'><option value=\'\'>-</option><option>Transferencia</option><option>Credito</option><option>Contado</option></select></div><button id=\'btn_timbrar\' onclick=\'guardar()\'>Timbrar CFDI</button><div id=\'confirmacion\'><h3>CFDI timbrado</h3><div id=\'cf\'></div></div></div></div></div><script>function agregar(){var e=document.getElementById(\'estado\');if(e){e.textContent=\'En carrito: \'+(document.getElementById(\'f_producto\').value||\'\')+\' x \'+(document.getElementById(\'f_cantidad\').value||\'\');}}function guardar(){var c=document.getElementById(\'cf\');c.innerHTML=\'\';document.querySelectorAll(\'input,select\').forEach(function(el){var f=document.createElement(\'div\');f.className=\'cf\';f.innerHTML=\'<span class="cn">\'+el.name+\'</span><span class="cv" data-campo="\'+el.name+\'">\'+(el.value||\'-\')+\'</span>\';c.appendChild(f);});document.getElementById(\'confirmacion\').style.display=\'block\';document.body.setAttribute(\'data-guardado\',\'true\');}</script></body></html>'

PRODUCTO_HTML = '<!DOCTYPE html><html lang=\'es\'><head><meta charset=\'UTF-8\'><title>ProveedorLink - Ficha de Producto</title><style>*{box-sizing:border-box;margin:0;padding:0}body{font-family:\'Segoe UI\',Arial,sans-serif;background:#fafaf9}header{background:#7c2d12;color:#fff;padding:14px 28px;display:flex;align-items:center;gap:14px}header h1{font-size:15px;font-weight:600}.crumb{color:rgba(255,255,255,.6);font-size:12px}.wrap{max-width:900px;margin:24px auto;padding:0 18px}.product-layout{display:grid;grid-template-columns:300px 1fr;gap:0;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 16px rgba(0,0,0,.08)}.product-hero{background:linear-gradient(160deg,#431407,#9a3412);padding:28px 24px;display:flex;flex-direction:column;gap:16px;justify-content:center}.img-placeholder{background:rgba(255,255,255,.1);border-radius:10px;height:130px;display:flex;align-items:center;justify-content:center;font-size:48px}.hero-name{color:#fff;font-size:18px;font-weight:700;line-height:1.35}.hero-price{background:rgba(255,255,255,.15);border-radius:8px;padding:10px 14px;color:#fed7aa;font-size:24px;font-weight:800}.product-specs{padding:28px}.specs-ttl{font-size:10px;font-weight:700;color:#9a3412;letter-spacing:1.5px;text-transform:uppercase;margin-bottom:16px;padding-bottom:8px;border-bottom:2px solid #fde8d0}.spec-row{display:flex;padding:10px 0;border-bottom:1px solid #fef3e2;align-items:center}.spec-row:last-child{border-bottom:none}.spec-k{flex:0 0 48%;font-size:12px;color:#78350f;font-weight:600}.spec-v{flex:1;font-size:14px;font-weight:700;color:#1c1917}.cat-badge{display:inline-block;background:#fde68a;color:#92400e;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700}</style></head><body><header><h1>ProveedorLink</h1><span class=\'crumb\'>Catalogo &rsaquo; Ficha de producto</span></header><div class=\'wrap\'><div class=\'product-layout\'><div class=\'product-hero\'><div class=\'img-placeholder\'>&#128230;</div><div class=\'hero-name\' id=\'hero-desc\'>-</div><div class=\'hero-price\' id=\'hero-price\'>-</div></div><div class=\'product-specs\'><div class=\'specs-ttl\'>Especificaciones del articulo</div><div class=\'spec-row\'><span class=\'spec-k\'>SKU proveedor</span><span class=\'spec-v\' id=\'sku\'></span></div><div class=\'spec-row\'><span class=\'spec-k\'>Descripcion</span><span class=\'spec-v\' id=\'descripcion\'></span></div><div class=\'spec-row\'><span class=\'spec-k\'>Categoria</span><span class=\'spec-v\' id=\'categoria\'></span></div><div class=\'spec-row\'><span class=\'spec-k\'>Precio unitario</span><span class=\'spec-v\' id=\'precio\'></span></div><div class=\'spec-row\'><span class=\'spec-k\'>Unidad</span><span class=\'spec-v\' id=\'unidad\'></span></div><div class=\'spec-row\'><span class=\'spec-k\'>Codigo de barras</span><span class=\'spec-v\' id=\'ean\'></span></div><div class=\'spec-row\'><span class=\'spec-k\'>Marca</span><span class=\'spec-v\' id=\'marca\'></span></div></div></div></div><script>var DATOS={"ART-1001": {"sku": "ART-1001", "descripcion": "Refresco Cola 600ml", "categoria": "Bebidas", "precio": "$12.50", "unidad": "Pieza", "ean": "7501000111001", "marca": "Topo Chico"}, "ART-1002": {"sku": "ART-1002", "descripcion": "Agua Mineral 1L", "categoria": "Bebidas", "precio": "$18.00", "unidad": "Pieza", "ean": "7501000111002", "marca": "Topo Chico"}, "ART-1003": {"sku": "ART-1003", "descripcion": "Jugo Naranja 1.5L", "categoria": "Jugos", "precio": "$27.90", "unidad": "Pieza", "ean": "7501000111003", "marca": "Del Valle"}, "ART-1004": {"sku": "ART-1004", "descripcion": "Botella Agua 20L", "categoria": "Garrafones", "precio": "$45.00", "unidad": "Pieza", "ean": "7501000111004", "marca": "Ciel"}};var id=new URLSearchParams(location.search).get(\'id\')||\'ART-1001\';var d=DATOS[id]||DATOS[\'ART-1001\'];["sku", "descripcion", "categoria", "precio", "unidad", "ean", "marca"].forEach(function(k){document.getElementById(k).textContent=d[k];});document.getElementById(\'hero-desc\').textContent=d[\'descripcion\'];document.getElementById(\'hero-price\').textContent=d[\'precio\'];document.body.setAttribute(\'data-cargado\',\'true\');</script></body></html>'

CLIENTES_DIR_HTML = '<!DOCTYPE html><html lang=\'es\'><head><meta charset=\'UTF-8\'><title>ClienteNet - Perfil de Cliente</title><style>*{box-sizing:border-box;margin:0;padding:0}body{font-family:\'Segoe UI\',Arial,sans-serif;background:#eef2ff}header{background:linear-gradient(135deg,#312e81,#4338ca);color:#fff;padding:14px 28px;display:flex;align-items:center;justify-content:space-between}header h1{font-size:15px;font-weight:600}.nav-crumb{font-size:11px;color:rgba(255,255,255,.6)}.wrap{max-width:640px;margin:24px auto;padding:0 18px}.profile-card{background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 20px rgba(67,56,202,.15)}.profile-top{background:linear-gradient(135deg,#4338ca,#7c3aed);padding:26px 28px;display:flex;gap:18px;align-items:flex-start}.avatar{width:56px;height:56px;border-radius:50%;background:rgba(255,255,255,.25);display:flex;align-items:center;justify-content:center;font-size:20px;font-weight:700;color:#fff;flex-shrink:0;border:2px solid rgba(255,255,255,.4)}.profile-info .name{color:#fff;font-size:18px;font-weight:700;margin-bottom:6px;line-height:1.2}.profile-info .badge{background:rgba(255,255,255,.2);color:#e0e7ff;padding:3px 10px;border-radius:12px;font-size:11px;font-weight:600}.profile-fields{padding:22px 28px}.section-lbl{font-size:10px;font-weight:700;color:#6366f1;letter-spacing:1.5px;text-transform:uppercase;margin-bottom:14px;padding-bottom:6px;border-bottom:2px solid #e0e7ff}.pf{display:flex;padding:11px 0;border-bottom:1px solid #e0e7ff;align-items:center}.pf:last-child{border-bottom:none}.pfl{flex:0 0 44%;font-size:11px;color:#6366f1;font-weight:700;text-transform:uppercase;letter-spacing:.3px}.pfv{flex:1;font-size:15px;font-weight:700;color:#1e1b4b}</style></head><body><header><h1>ClienteNet CRM</h1><span class=\'nav-crumb\'>Directorio &rsaquo; Perfil</span></header><div class=\'wrap\'><div class=\'profile-card\'><div class=\'profile-top\'><div class=\'avatar\' id=\'avatar-initials\'>?</div><div class=\'profile-info\'><div class=\'name\' id=\'profile-display\'>Cargando...</div><span class=\'badge\'>Cliente activo</span></div></div><div class=\'profile-fields\'><div class=\'section-lbl\'>Datos del cliente</div><div class=\'pf\'><span class=\'pfl\'>Nombre comercial</span><span class=\'pfv\' id=\'nombre\'></span></div><div class=\'pf\'><span class=\'pfl\'>Clave de cliente</span><span class=\'pfv\' id=\'clave\'></span></div><div class=\'pf\'><span class=\'pfl\'>RFC</span><span class=\'pfv\' id=\'rfc\'></span></div><div class=\'pf\'><span class=\'pfl\'>Regimen</span><span class=\'pfv\' id=\'regimen\'></span></div><div class=\'pf\'><span class=\'pfl\'>Zona</span><span class=\'pfv\' id=\'zona\'></span></div></div></div></div><script>var DATOS={"DIR-01": {"nombre": "Walmart de Mexico", "clave": "WMX-001", "rfc": "wme9912319x3", "regimen": "Personas Morales", "zona": "Centro"}, "DIR-02": {"nombre": "Soriana Hiper", "clave": "SOR-014", "rfc": "sho850101kk1", "regimen": "Personas Morales", "zona": "Norte"}, "DIR-03": {"nombre": "Chedraui Selecto", "clave": "CHS-220", "rfc": "chs030404tt8", "regimen": "RESICO", "zona": "Sureste"}, "DIR-04": {"nombre": "OXXO Tiendas", "clave": "OXO-777", "rfc": "oxo991010mm2", "regimen": "Personas Morales", "zona": "Bajio"}};var id=new URLSearchParams(location.search).get(\'id\')||\'DIR-01\';var d=DATOS[id]||DATOS[\'DIR-01\'];["nombre", "clave", "rfc", "regimen", "zona"].forEach(function(k){document.getElementById(k).textContent=d[k];});var av=(d[\'nombre\']||\'?\').split(\' \').map(function(w){return w[0]||\'\';}).join(\'\').slice(0,2).toUpperCase();document.getElementById(\'avatar-initials\').textContent=av;document.getElementById(\'profile-display\').textContent=d[\'nombre\']||\'\';document.body.setAttribute(\'data-cargado\',\'true\');</script></body></html>'

LISTA_COMPRA_HTML = '<!DOCTYPE html><html lang=\'es\'><head><meta charset=\'UTF-8\'><title>ReqFast - Requisicion de Compra</title><style>*{box-sizing:border-box;margin:0;padding:0}body{font-family:\'Segoe UI\',Arial,sans-serif;background:#f0fdfa}header{background:#0f766e;color:#fff;padding:14px 28px;display:flex;align-items:center;justify-content:space-between}header h1{font-size:15px;font-weight:600}.hright{font-size:11px;color:rgba(255,255,255,.7)}.wrap{max-width:540px;margin:28px auto;padding:0 18px}.ticket{background:#fff;border-radius:12px;box-shadow:0 2px 16px rgba(0,0,0,.08);overflow:hidden}.ticket-stripe{height:5px;background:linear-gradient(90deg,#0d9488,#0891b2)}.ticket-hdr{padding:16px 22px;border-bottom:1px solid #ccfbf1;display:flex;justify-content:space-between;align-items:center}.ticket-id{font-family:monospace;font-size:12px;color:#6b7280;font-weight:700}.badges{display:flex;gap:6px}.badge{padding:3px 10px;border-radius:20px;font-size:11px;font-weight:700}.badge-pend{background:#fef9c3;color:#854d0e}.badge-prio{background:#fce7f3;color:#9d174d}.ticket-body{padding:20px 22px}.body-lbl{font-size:10px;font-weight:700;color:#0f766e;letter-spacing:1.5px;text-transform:uppercase;margin-bottom:14px}.req-row{display:flex;padding:14px 0;border-bottom:1px solid #f0fdfa;align-items:center}.req-row:last-child{border-bottom:none}.req-k{flex:0 0 42%;font-size:11px;font-weight:700;color:#0f766e;text-transform:uppercase;letter-spacing:.3px}.req-v{flex:1;font-size:20px;font-weight:800;color:#0f2d2a}.ticket-ftr{background:#f0fdfa;padding:9px 22px;font-size:11px;color:#9ca3af;display:flex;justify-content:space-between}</style></head><body><header><h1>ReqFast</h1><span class=\'hright\'>Portal de Requisiciones</span></header><div class=\'wrap\'><div class=\'ticket\'><div class=\'ticket-stripe\'></div><div class=\'ticket-hdr\'><span class=\'ticket-id\' id=\'ticket-num\'>REQ-LC-01</span><div class=\'badges\'><span class=\'badge badge-pend\'>Pendiente</span><span class=\'badge badge-prio\'>Alta</span></div></div><div class=\'ticket-body\'><div class=\'body-lbl\'>Detalle de requisicion</div><div class=\'req-row\'><span class=\'req-k\'>Producto</span><span class=\'req-v\' id=\'producto_src\'></span></div><div class=\'req-row\'><span class=\'req-k\'>Cantidad</span><span class=\'req-v\' id=\'cantidad_src\'></span></div></div><div class=\'ticket-ftr\'><span>Solicitante: Compras</span><span>Urgente</span></div></div></div><script>var DATOS={"LC-01": {"producto_src": "Refresco Cola 600ml", "cantidad_src": "24"}, "LC-02": {"producto_src": "Agua Mineral 1L", "cantidad_src": "12"}, "LC-03": {"producto_src": "Jugo Naranja 1.5L", "cantidad_src": "36"}, "LC-04": {"producto_src": "Botella Agua 20L", "cantidad_src": "6"}};var id=new URLSearchParams(location.search).get(\'id\')||\'LC-01\';var d=DATOS[id]||DATOS[\'LC-01\'];["producto_src", "cantidad_src"].forEach(function(k){document.getElementById(k).textContent=d[k];});document.getElementById(\'ticket-num\').textContent=\'REQ-\'+id;document.body.setAttribute(\'data-cargado\',\'true\');</script></body></html>'

CATALOGO_HTML = '<!DOCTYPE html><html lang=\'es\'><head><meta charset=\'UTF-8\'><title>SistemaAC - Catalogo de Articulos</title><style>*{box-sizing:border-box;margin:0;padding:0}body{font-family:\'Segoe UI\',Arial,sans-serif;background:#0f172a;color:#e2e8f0}header{background:#0b1120;color:#f1f5f9;padding:13px 28px;border-bottom:1px solid #1e293b}header h1{font-size:15px;font-weight:600;color:#f8fafc}.wrap{max-width:700px;margin:24px auto;padding:0 18px}.card{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:22px 24px}.card-ttl{font-size:10px;font-weight:700;color:#f59e0b;text-transform:uppercase;letter-spacing:1px;margin-bottom:16px}.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.form-row{margin-bottom:11px}label{display:block;font-size:10px;color:#94a3b8;margin-bottom:4px;font-weight:700;text-transform:uppercase;letter-spacing:.3px}input,select{width:100%;padding:9px 11px;font-size:13px;border:1px solid #334155;border-radius:7px;background:#0f172a;color:#f1f5f9}input:focus,select:focus{outline:none;border-color:#f59e0b}button{margin-top:4px;background:#f59e0b;color:#0f172a;border:none;padding:10px 22px;font-size:13px;border-radius:7px;cursor:pointer;font-weight:800}#confirmacion{margin-top:14px;background:#0c2a20;border:1px solid #14503b;border-radius:8px;padding:14px;display:none}#confirmacion h3{font-size:12px;color:#6ee7b7;margin:0 0 8px}.cf{display:flex;padding:4px 0;font-size:12px;border-bottom:1px solid #14503b}.cf:last-child{border-bottom:none}.cn{flex:0 0 45%;color:#94a3b8}.cv{flex:1;font-weight:600;color:#e2e8f0}</style></head><body><header><h1>SistemaAC &mdash; Catalogo de Articulos</h1></header><div class=\'wrap\'><div class=\'card\'><div class=\'card-ttl\'>Alta de nuevo articulo</div><div class=\'form-row\'><label for=\'f_clave\'>Clave de articulo</label><input id=\'f_clave\' name=\'clave_articulo\' autocomplete=\'off\'></div><div class=\'form-row\'><label for=\'f_nombre\'>Nombre</label><input id=\'f_nombre\' name=\'nombre\' autocomplete=\'off\'></div><div class=\'form-row\'><label for=\'f_familia\'>Familia</label><input id=\'f_familia\' name=\'familia\' autocomplete=\'off\'></div><div class=\'form-grid\'><div class=\'form-row\'><label for=\'f_precio\'>Precio de lista</label><input id=\'f_precio\' name=\'precio_lista\' autocomplete=\'off\'></div><div class=\'form-row\'><label for=\'f_um\'>Unidad de medida</label><select id=\'f_um\' name=\'um\'><option value=\'\'>-</option><option>Pieza</option><option>Caja</option><option>Litro</option><option>Kilogramo</option></select></div></div><div class=\'form-row\'><label for=\'f_ean\'>EAN</label><input id=\'f_ean\' name=\'ean\' autocomplete=\'off\'></div><div class=\'form-row\'><label for=\'f_marca\'>Marca</label><input id=\'f_marca\' name=\'marca\' autocomplete=\'off\'></div><button id=\'btn_alta\' onclick=\'guardar()\'>Dar de alta</button><div id=\'confirmacion\'><h3>Articulo dado de alta</h3><div id=\'cf\'></div></div></div></div><script>function agregar(){var e=document.getElementById(\'estado\');if(e){e.textContent=\'En carrito: \'+(document.getElementById(\'f_producto\').value||\'\')+\' x \'+(document.getElementById(\'f_cantidad\').value||\'\');}}function guardar(){var c=document.getElementById(\'cf\');c.innerHTML=\'\';document.querySelectorAll(\'input,select\').forEach(function(el){var f=document.createElement(\'div\');f.className=\'cf\';f.innerHTML=\'<span class="cn">\'+el.name+\'</span><span class="cv" data-campo="\'+el.name+\'">\'+(el.value||\'-\')+\'</span>\';c.appendChild(f);});document.getElementById(\'confirmacion\').style.display=\'block\';document.body.setAttribute(\'data-guardado\',\'true\');}</script></body></html>'

CRM_HTML = '<!DOCTYPE html><html lang=\'es\'><head><meta charset=\'UTF-8\'><title>SistemaAC - CRM de Clientes</title><style>*{box-sizing:border-box;margin:0;padding:0}body{font-family:\'Segoe UI\',Arial,sans-serif;background:#f5f3ff}header{background:linear-gradient(135deg,#2e1065,#4c1d95);color:#fff;padding:13px 28px}header h1{font-size:15px;font-weight:600}.wrap{max-width:680px;margin:24px auto;padding:0 18px}.crm-card{background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(109,40,217,.1)}.crm-top{background:linear-gradient(135deg,#6d28d9,#7c3aed);padding:18px 24px;display:flex;align-items:center;gap:14px}.crm-icon{width:44px;height:44px;border-radius:50%;background:rgba(255,255,255,.2);display:flex;align-items:center;justify-content:center;font-size:20px}.crm-top-txt h2{color:#fff;font-size:15px;font-weight:700;margin:0}.crm-top-txt p{color:rgba(255,255,255,.7);font-size:11px;margin:2px 0 0}.crm-body{padding:20px 24px}.crm-sec{margin-bottom:18px}.crm-sec-lbl{font-size:10px;font-weight:700;color:#7c3aed;text-transform:uppercase;letter-spacing:.8px;margin-bottom:10px;padding-bottom:5px;border-bottom:2px solid #ede9fe}.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.form-row{margin-bottom:10px}label{display:block;font-size:10px;color:#7c3aed;margin-bottom:3px;font-weight:700}input,select{width:100%;padding:8px 10px;font-size:13px;border:1px solid #ede9fe;border-radius:6px;background:#faf5ff;color:#1e1b4b}input:focus,select:focus{outline:none;border-color:#7c3aed;background:#fff}button{background:#7c3aed;color:#fff;border:none;padding:10px 22px;font-size:13px;border-radius:6px;cursor:pointer;font-weight:700}#confirmacion{margin-top:14px;background:#f5f3ff;border:1px solid #c4b5fd;border-radius:8px;padding:14px;display:none}#confirmacion h3{font-size:12px;color:#4c1d95;margin:0 0 8px}.cf{display:flex;padding:4px 0;font-size:12px;border-bottom:1px solid #ede9fe}.cf:last-child{border-bottom:none}.cn{flex:0 0 45%;color:#9ca3af}.cv{flex:1;font-weight:600;color:#1e1b4b}</style></head><body><header><h1>SistemaAC &mdash; CRM de Clientes</h1></header><div class=\'wrap\'><div class=\'crm-card\'><div class=\'crm-top\'><div class=\'crm-icon\'>&#128101;</div><div class=\'crm-top-txt\'><h2>Alta de cliente</h2><p>Complete los datos del nuevo cliente</p></div></div><div class=\'crm-body\'><div class=\'crm-sec\'><div class=\'crm-sec-lbl\'>Identificacion</div><div class=\'form-row\'><label for=\'f_clave2\'>Clave de cliente</label><input id=\'f_clave2\' name=\'clave_cliente\' autocomplete=\'off\'></div><div class=\'form-row\'><label for=\'f_razon2\'>Razon social</label><input id=\'f_razon2\' name=\'razon_social\' autocomplete=\'off\'></div></div><div class=\'crm-sec\'><div class=\'crm-sec-lbl\'>Datos fiscales y cobertura</div><div class=\'form-grid\'><div class=\'form-row\'><label for=\'f_rfc2\'>RFC</label><input id=\'f_rfc2\' name=\'rfc\' autocomplete=\'off\'></div><div class=\'form-row\'><label for=\'f_regimen\'>Regimen fiscal</label><select id=\'f_regimen\' name=\'regimen\'><option value=\'\'>-</option><option>General de Ley</option><option>RIF</option><option>Personas Morales</option><option>RESICO</option></select></div></div><div class=\'form-row\'><label for=\'f_zona\'>Zona</label><input id=\'f_zona\' name=\'zona\' autocomplete=\'off\'></div></div><button id=\'btn_registrar\' onclick=\'guardar()\'>Registrar cliente</button><div id=\'confirmacion\'><h3>Cliente registrado</h3><div id=\'cf\'></div></div></div></div></div><script>function agregar(){var e=document.getElementById(\'estado\');if(e){e.textContent=\'En carrito: \'+(document.getElementById(\'f_producto\').value||\'\')+\' x \'+(document.getElementById(\'f_cantidad\').value||\'\');}}function guardar(){var c=document.getElementById(\'cf\');c.innerHTML=\'\';document.querySelectorAll(\'input,select\').forEach(function(el){var f=document.createElement(\'div\');f.className=\'cf\';f.innerHTML=\'<span class="cn">\'+el.name+\'</span><span class="cv" data-campo="\'+el.name+\'">\'+(el.value||\'-\')+\'</span>\';c.appendChild(f);});document.getElementById(\'confirmacion\').style.display=\'block\';document.body.setAttribute(\'data-guardado\',\'true\');}</script></body></html>'

TIENDA_HTML = '<!DOCTYPE html><html lang=\'es\'><head><meta charset=\'UTF-8\'><title>SistemaAC - Compra en Tienda</title><style>*{box-sizing:border-box;margin:0;padding:0}body{font-family:\'Segoe UI\',Arial,sans-serif;background:#fff7ed}header{background:#c2410c;color:#fff;padding:13px 28px;display:flex;align-items:center;gap:14px}header h1{font-size:15px;font-weight:600}.tagline{font-size:11px;color:rgba(255,255,255,.7)}.wrap{max-width:700px;margin:24px auto;padding:0 18px;display:grid;grid-template-columns:1fr 280px;gap:20px}.checkout-form{background:#fff;border:1px solid #fed7aa;border-radius:10px;padding:22px 24px}.form-ttl{font-size:13px;font-weight:700;color:#9a3412;margin-bottom:16px;padding-bottom:8px;border-bottom:2px solid #fde8d0}.form-row{margin-bottom:12px}label{display:block;font-size:11px;color:#92400e;margin-bottom:4px;font-weight:700}input,select{width:100%;padding:9px 11px;font-size:13px;border:1px solid #fed7aa;border-radius:7px;background:#fff7ed;color:#1c1917}input:focus,select:focus{outline:none;border-color:#ea580c;background:#fff}.btn-row{display:flex;gap:10px;margin-top:8px}.btn-add{background:#ea580c;color:#fff;border:none;padding:10px 18px;font-size:13px;border-radius:7px;cursor:pointer;font-weight:700}.btn-fin{background:#1c1917;color:#fff;border:none;padding:10px 18px;font-size:13px;border-radius:7px;cursor:pointer;font-weight:700}.summary{background:#fff;border:1px solid #fed7aa;border-radius:10px;padding:20px;height:fit-content}.sum-ttl{font-size:12px;font-weight:700;color:#9a3412;margin-bottom:12px}.sum-row{display:flex;justify-content:space-between;font-size:12px;color:#6b7280;margin-bottom:6px}.cart-status{background:#fef3c7;border-radius:6px;padding:8px 10px;font-size:12px;color:#92400e;margin-top:10px}#confirmacion{margin-top:14px;background:#fff7ed;border:1px solid #fdba74;border-radius:8px;padding:14px;display:none}#confirmacion h3{font-size:12px;color:#9a3412;margin:0 0 8px}.cf{display:flex;padding:4px 0;font-size:12px;border-bottom:1px solid #fde8d0}.cf:last-child{border-bottom:none}.cn{flex:0 0 45%;color:#92400e}.cv{flex:1;font-weight:700;color:#1c1917}</style></head><body><header><h1>SistemaAC &mdash; Compra en Tienda</h1><span class=\'tagline\'>Canal de ventas directas</span></header><div class=\'wrap\'><div class=\'checkout-form\'><div class=\'form-ttl\'>Nueva orden de compra</div><div class=\'form-row\'><label for=\'f_producto\'>Producto</label><select id=\'f_producto\' name=\'producto\'><option value=\'\'>Selecciona un producto</option><option>Refresco Cola 600ml</option><option>Agua Mineral 1L</option><option>Jugo Naranja 1.5L</option><option>Botella Agua 20L</option></select></div><div class=\'form-row\'><label for=\'f_cantidad\'>Cantidad</label><input id=\'f_cantidad\' name=\'cantidad\' autocomplete=\'off\' placeholder=\'Ej. 24\'></div><div class=\'btn-row\'><button class=\'btn-add\' id=\'btn_agregar\' onclick=\'agregar()\'>+ Agregar al carrito</button><button class=\'btn-fin\' id=\'btn_finalizar\' onclick=\'guardar()\'>Finalizar compra</button></div><div id=\'estado\' style=\'margin-top:8px;font-size:13px;color:#92400e\'></div><div id=\'confirmacion\'><h3>Compra registrada</h3><div id=\'cf\'></div></div></div><div class=\'summary\'><div class=\'sum-ttl\'>Resumen del carrito</div><div class=\'sum-row\'><span>Subtotal</span><span>-</span></div><div class=\'sum-row\'><span>IVA (16%)</span><span>-</span></div><div class=\'sum-row\'><span style="font-weight:700;color:#1c1917">Total</span><span style="font-weight:700;color:#1c1917">-</span></div><div class=\'cart-status\' id=\'cart-summary\'>Carrito vacio</div></div></div><script>function agregar(){var e=document.getElementById(\'estado\');if(e){e.textContent=\'En carrito: \'+(document.getElementById(\'f_producto\').value||\'\')+\' x \'+(document.getElementById(\'f_cantidad\').value||\'\');}}function guardar(){var c=document.getElementById(\'cf\');c.innerHTML=\'\';document.querySelectorAll(\'input,select\').forEach(function(el){var f=document.createElement(\'div\');f.className=\'cf\';f.innerHTML=\'<span class="cn">\'+el.name+\'</span><span class="cv" data-campo="\'+el.name+\'">\'+(el.value||\'-\')+\'</span>\';c.appendChild(f);});document.getElementById(\'confirmacion\').style.display=\'block\';document.body.setAttribute(\'data-guardado\',\'true\');}</script></body></html>'


# ==================== SERVIDOR EN MEMORIA ====================
def _hacer_handler(rutas):
    class H(BaseHTTPRequestHandler):
        ROUTES = rutas
        def do_GET(self):
            ruta = self.path.split("?")[0]
            if ruta == "/":
                ruta = "/index.html"
            html = self.ROUTES.get(ruta)
            if html is None:
                self.send_error(404); return
            data = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        def log_message(self, *a):
            pass
    return H


def iniciar_servidores():
    externos = {"/index.html": PORTALES_ROOT, "/oc.html": OC_HTML, "/cliente.html": CLIENTE_HTML,
                "/producto.html": PRODUCTO_HTML, "/clientes_dir.html": CLIENTES_DIR_HTML,
                "/lista_compra.html": LISTA_COMPRA_HTML}
    internos = {"/index.html": INTERNOS_ROOT, "/orden.html": ORDEN_HTML, "/factura.html": FACTURA_HTML,
                "/catalogo.html": CATALOGO_HTML, "/crm.html": CRM_HTML, "/tienda.html": TIENDA_HTML}
    s1 = ThreadingHTTPServer(("127.0.0.1", 8000), _hacer_handler(externos))
    s2 = ThreadingHTTPServer(("127.0.0.1", 8001), _hacer_handler(internos))
    threading.Thread(target=s1.serve_forever, daemon=True).start()
    threading.Thread(target=s2.serve_forever, daemon=True).start()
    time.sleep(0.6)
    print("Sistemas EXTERNOS -> http://localhost:8000")
    print("Sistemas INTERNOS -> http://localhost:8001")


# ==================== JS QUE CORRE EN EL NAVEGADOR ====================
# Extractor GENERICO del origen: maneja tablas, formularios y pares etiqueta/valor.
JS_EXTRAER = """
() => {
  const out = []; const visto = new Set();
  const push = (etiqueta, valor, selector) => {
    valor = (valor || '').trim(); etiqueta = (etiqueta || '').trim();
    if (!valor || !selector || visto.has(selector)) return;
    out.push({ etiqueta: etiqueta, valor: valor, selector: selector }); visto.add(selector);
  };
  // Tablas (thead th -> tbody td)
  document.querySelectorAll('table').forEach((t) => {
    const heads = Array.from(t.querySelectorAll('thead th, thead td')).map((h) => h.textContent.trim());
    t.querySelectorAll('tbody tr').forEach((tr, ri) => {
      Array.from(tr.children).forEach((td, ci) => {
        if (!td.id) td.id = 'celda_' + ri + '_' + ci;
        push(heads[ci] || ('col' + ci), td.textContent, '#' + td.id);
      });
    });
  });
  // dl/dt/dd (definicion)
  document.querySelectorAll('dt').forEach((dt) => {
    const dd = dt.nextElementSibling;
    if (dd && dd.tagName === 'DD' && dd.id) {
      push(dt.textContent.trim(), dd.textContent.trim(), '#' + dd.id);
    }
  });
  // Formularios (label[for] + input/select)
  document.querySelectorAll('input, select, textarea').forEach((el) => {
    if (!el.id && !el.name) return;
    const sel = el.id ? ('#' + el.id) : ('[name="' + el.name + '"]');
    let lab = '';
    if (el.id) { const l = document.querySelector('label[for="' + el.id + '"]'); if (l) lab = l.textContent; }
    if (!lab) lab = el.getAttribute('aria-label') || el.placeholder || el.name || '';
    push(lab, el.value, sel);
  });
  // Par etiqueta/valor por proximidad (hoja con id, hermano previo = etiqueta)
  document.querySelectorAll('[id]').forEach((el) => {
    if (el.children.length > 0) return;
    if (['INPUT','SELECT','TEXTAREA','TABLE','TD','TH','BODY','HTML','DT','DD'].includes(el.tagName)) return;
    const valor = el.textContent.trim();
    if (!valor || valor.length > 120) return;
    let lab = '';
    const prev = el.previousElementSibling;
    if (prev && prev.children.length === 0) lab = prev.textContent;
    if (!lab && el.parentElement) {
      const cand = Array.from(el.parentElement.children).find((c) => c !== el && c.children.length === 0 && c.textContent.trim());
      if (cand) lab = cand.textContent;
    }
    push(lab, valor, '#' + el.id);
  });
  return out;
}
"""

# Grabador GENERICO: registra cualquier accion del usuario en el destino.
JS_RECORDER = """
() => {
  window.__traza = [];
  const etiquetaDe = (el) => {
    let t = '';
    if (el.id) { const l = document.querySelector('label[for="' + el.id + '"]'); if (l) t = l.textContent; }
    if (!t) t = el.getAttribute('aria-label') || el.placeholder || el.name || '';
    return (t || '').trim();
  };
  const reg = (accion, el, valor) => {
    const paso = {
      accion: accion,
      objetivo_tipo: el.tagName.toLowerCase() === 'select' ? 'select' : (el.type || (el.tagName.toLowerCase() === 'button' ? 'button' : 'text')),
      objetivo_name: el.name || null,
      objetivo_selector: el.id ? ('#' + el.id) : (el.name ? ('[name="' + el.name + '"]') : null),
      objetivo_etiqueta: etiquetaDe(el) || (el.textContent || '').trim().slice(0, 40),
      valor: (valor === undefined ? null : valor)
    };
    window.__traza.push(paso);
    console.log('[ACCION] ' + accion + ' :: ' + (paso.objetivo_etiqueta || paso.objetivo_name) + (paso.valor != null ? (' = ' + paso.valor) : ''));
  };
  document.addEventListener('change', (e) => {
    const el = e.target;
    if (['INPUT','SELECT','TEXTAREA'].includes(el.tagName))
      reg(el.tagName === 'SELECT' ? 'seleccionar' : 'escribir', el, el.value);
  }, true);
  document.addEventListener('click', (e) => {
    const b = e.target.closest('button, a, input[type=submit], input[type=button]');
    if (b) reg('clic', b, null);
  }, true);
}
"""


# ==================== TRANSFORMACIONES (deterministas) ====================
def aplicar_transform(valor, transform):
    if valor is None:
        return None
    t = transform or "copiar"
    if t == "copiar":
        return valor
    if t == "mayusculas":
        return valor.upper()
    if t == "minusculas":
        return valor.lower()
    if t == "numero_limpio":
        return re.sub(r"[^0-9.\-]", "", valor)
    if t == "fecha:DMY->YMD":
        p = valor.split("/")
        return (p[2] + "-" + p[1] + "-" + p[0]) if len(p) == 3 else valor
    if t == "fecha:YMD->DMY":
        p = valor.split("-")
        return (p[2] + "/" + p[1] + "/" + p[0]) if len(p) == 3 else valor
    if t.startswith("derivar:"):
        return _derivar(valor, t[len("derivar:"):])
    return valor


def _derivar(valor, regla):
    """Conversion arbitraria (ej. lookup) via Gemini. Solo se usa si el skill lo pide."""
    try:
        cli, modelo = _cliente_gemini()
        from google.genai import types
        r = cli.models.generate_content(
            model=modelo,
            contents=("Aplica esta conversion a un valor y responde SOLO con el resultado, sin explicar.\n"
                      "Regla: " + regla + "\nValor de entrada: " + str(valor)),
            config=types.GenerateContentConfig(temperature=0),
        )
        return (r.text or "").strip()
    except Exception:
        return valor


# ==================== GEMINI: generalizar la demostracion en un skill ====================
def _cliente_gemini():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass
    from google import genai
    key = GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise SystemExit("Falta tu API key de Gemini. Pegala en GEMINI_API_KEY o usa variable de entorno "
                         "(la sacas gratis en https://aistudio.google.com/app/apikey).")
    return genai.Client(api_key=key), GEMINI_MODELO


def inferir_enriquecimiento(datos_origen, traza):
    """Gemini agrega a cada accion: de donde salio el valor y que transformacion se aplico."""
    from google.genai import types
    cli, modelo = _cliente_gemini()
    prompt = (
        "Eres un agente que aprende un PROCEDIMIENTO observando UNA demostracion entre dos sistemas web. "
        "No tienes reglas previas.\n\n"
        "DATOS DISPONIBLES EN EL ORIGEN (lo que el usuario podia leer):\n"
        + json.dumps(datos_origen, ensure_ascii=False, indent=2) +
        "\n\nACCIONES QUE EL USUARIO REALIZO EN EL DESTINO, EN ORDEN:\n"
        + json.dumps([{"i": i, "accion": a["accion"], "objetivo_selector": a.get("objetivo_selector"),
                       "objetivo_etiqueta": a.get("objetivo_etiqueta"), "valor": a.get("valor")}
                      for i, a in enumerate(traza)], ensure_ascii=False, indent=2) +
        "\n\nPara CADA accion de tipo 'escribir' o 'seleccionar', deduce: "
        "(1) de que dato del origen salio el valor (compara valores y semantica de etiquetas), y "
        "(2) si hubo una TRANSFORMACION, comparando el valor del origen con el valor tecleado.\n"
        "Vocabulario de transform (elige uno): copiar, mayusculas, minusculas, numero_limpio, "
        "fecha:DMY->YMD, fecha:YMD->DMY, derivar:<regla breve>.\n"
        "Si el valor NO proviene del origen, pon origen_selector=null y literal=<el texto>. "
        "Para 'clic' usa origen_selector=null, transform=copiar, literal=null.\n\n"
        "Devuelve UNICAMENTE un arreglo JSON, UN objeto por accion EN EL MISMO ORDEN, con: "
        '{"i": <indice>, "objetivo_selector": "...", "origen_selector": "... o null", '
        '"origen_etiqueta": "... o null", "transform": "...", "literal": "... o null", "razon": "..."}'
    )
    r = cli.models.generate_content(
        model=modelo, contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0),
    )
    txt = (r.text or "").strip()
    if txt.startswith("```"):
        txt = txt.strip("`"); txt = txt[txt.find("["):txt.rfind("]") + 1]
    return json.loads(txt)


def construir_skill(nombre, proc, datos_origen, traza, enr):
    por_i = {}
    for e in enr:
        if isinstance(e.get("i"), int):
            por_i[e["i"]] = e
    por_sel = {e.get("objetivo_selector"): e for e in enr if e.get("objetivo_selector")}
    pasos = []
    for i, a in enumerate(traza):
        e = por_i.get(i) or por_sel.get(a.get("objetivo_selector")) or {}
        pasos.append({
            "accion": a["accion"],
            "objetivo_tipo": a.get("objetivo_tipo"),
            "objetivo_selector": a.get("objetivo_selector"),
            "objetivo_name": a.get("objetivo_name"),
            "objetivo_etiqueta": a.get("objetivo_etiqueta"),
            "origen_selector": None if a["accion"] == "clic" else e.get("origen_selector"),
            "origen_etiqueta": None if a["accion"] == "clic" else e.get("origen_etiqueta"),
            "transform": "copiar" if a["accion"] == "clic" else (e.get("transform") or "copiar"),
            "literal": None if a["accion"] == "clic" else e.get("literal"),
        })
    return {
        "nombre": nombre, "titulo": proc["titulo"],
        "origen_url_template": proc["origen_url_template"],
        "destino_url": proc["destino_url"], "pasos": pasos,
    }


# ==================== LOCALIZAR Y EJECUTAR (reproduccion robusta) ====================
def localizar(pag, paso):
    for sel in [paso.get("objetivo_selector"),
                ('[name="' + paso["objetivo_name"] + '"]') if paso.get("objetivo_name") else None]:
        if not sel:
            continue
        loc = pag.locator(sel)
        if loc.count() > 0:
            return loc.first
    et = paso.get("objetivo_etiqueta")
    if et:
        lab = pag.locator("label", has_text=et)
        if lab.count() > 0:
            forid = lab.first.get_attribute("for")
            if forid:
                loc = pag.locator("#" + forid)
                if loc.count() > 0:
                    return loc.first
    return None


def valor_para(paso, origen_val, origen_val_et):
    if paso.get("literal"):
        return paso["literal"]
    v = origen_val.get(paso.get("origen_selector"))
    if v is None and paso.get("origen_etiqueta"):
        v = origen_val_et.get(paso["origen_etiqueta"])
    return aplicar_transform(v, paso.get("transform"))


# ==================== COMANDOS ====================
def _abrir(p, headless):
    nav = p.chromium.launch(headless=headless)
    return nav, nav.new_context().new_page(), nav.new_context().new_page()


def grabar(p, nombre):
    if nombre not in PROCESOS:
        raise SystemExit("Proceso no configurado: " + nombre + ". Opciones: " + ", ".join(PROCESOS))
    proc = PROCESOS[nombre]
    nav, pag_o, pag_d = _abrir(p, headless=False)
    pag_d.on("console", lambda m: print("   " + m.text) if "[ACCION]" in m.text else None)

    print("\n=== GRABAR PROCESO: " + proc["titulo"] + " ===")
    pag_o.goto(proc["origen_url_template"].format(registro=proc["demo"]))
    pag_o.wait_for_load_state("networkidle")
    datos_origen = pag_o.evaluate(JS_EXTRAER)
    print("Datos que el sistema origen muestra:")
    for c in datos_origen:
        print("   - " + (c["etiqueta"] or "?") + ": " + c["valor"])

    pag_d.goto(proc["destino_url"])
    pag_d.evaluate(JS_RECORDER)
    print("\n>>> Realiza el proceso en la ventana DESTINO (una vez). El agente observa cada accion.")
    if '--web-mode' in sys.argv:
        run_id = sys.argv[sys.argv.index('--web-mode') + 1]
        flag = os.path.join('runs', run_id + '.done')
        os.makedirs('runs', exist_ok=True)
        print("Esperando senal del dashboard para continuar...")
        while not os.path.exists(flag):
            time.sleep(0.3)
        os.remove(flag)
    else:
        input(">>> Cuando termines (incluido el boton final), presiona ENTER aqui...\n")

    traza = pag_d.evaluate("() => window.__traza")
    if not traza:
        raise SystemExit("No capture acciones. Asegurate de teclear y dar clic en la ventana destino.")
    print("Generalizando la demostracion con Gemini...\n")
    enr = inferir_enriquecimiento(datos_origen, traza)
    skill = construir_skill(nombre, proc, datos_origen, traza, enr)

    os.makedirs(CARPETA_SKILLS, exist_ok=True)
    ruta = os.path.join(CARPETA_SKILLS, nombre + ".json")
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(skill, f, ensure_ascii=False, indent=2)

    print("=== SKILL APRENDIDO ===")
    for s in skill["pasos"]:
        if s["accion"] == "clic":
            print("   clic -> " + (s["objetivo_etiqueta"] or s["objetivo_selector"]))
        else:
            print("   " + (s["origen_etiqueta"] or "?").ljust(26) + " -> " +
                  (s["objetivo_name"] or s["objetivo_selector"]).ljust(18) +
                  " [" + s["transform"] + "]")
    print("\nGuardado en " + ruta)
    print("Ahora corre:  python agente_universal.py reproducir " + nombre + " " + proc["reproduce"])
    if '--web-mode' not in sys.argv:
        input("\nENTER para cerrar...")
    nav.close()


def _cargar_skill(nombre):
    ruta = os.path.join(CARPETA_SKILLS, nombre + ".json")
    if not os.path.exists(ruta):
        raise SystemExit("No existe el skill '" + nombre + "'. Grabalo primero con: grabar " + nombre)
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def _aplicar(pag_o, pag_d, skill, registro, verbose=True, lento=False):
    """Nucleo reutilizable: lee el origen del registro dado, aplica el skill en
    el destino y valida. Devuelve (ok, filas_validacion)."""
    pag_o.goto(skill["origen_url_template"].format(registro=registro))
    pag_o.wait_for_load_state("networkidle")
    datos = pag_o.evaluate(JS_EXTRAER)
    origen_val = {c["selector"]: c["valor"] for c in datos}
    origen_val_et = {c["etiqueta"]: c["valor"] for c in datos}

    pag_d.goto(skill["destino_url"])
    if verbose:
        print("Ejecutando el procedimiento aprendido (sin intervencion humana)...\n")
    for s in skill["pasos"]:
        el = localizar(pag_d, s)
        if el is None:
            if verbose:
                print("   (no encontre el objetivo de un paso: " + str(s.get("objetivo_etiqueta")) + ")")
            continue
        if s["accion"] == "clic":
            el.click()
        else:
            val = valor_para(s, origen_val, origen_val_et) or ""
            if s.get("objetivo_tipo") == "select":
                el.select_option(val)
            else:
                el.fill(val)
            if verbose:
                print("   " + (s["origen_etiqueta"] or s.get("origen_selector") or "literal").ljust(26) + " -> " +
                      (s["objetivo_name"] or "?").ljust(18) + " = " + val)
        pag_d.wait_for_timeout(200 if lento else 0)

    try:
        pag_d.wait_for_selector('body[data-guardado="true"]', timeout=3000)
    except Exception:
        pass

    ok = True
    filas = []
    for s in skill["pasos"]:
        if s["accion"] == "clic" or not s.get("objetivo_name"):
            continue
        esperado = valor_para(s, origen_val, origen_val_et)
        real = (pag_d.text_content('.cv[data-campo="' + s["objetivo_name"] + '"]') or "").strip()
        paso_ok = (esperado == real)
        ok = ok and paso_ok
        filas.append((s["objetivo_name"], esperado, real, paso_ok))
    return ok, filas


def reproducir(p, nombre, registro=None, headless=False, pausar=True):
    skill = _cargar_skill(nombre)
    if not registro:
        registro = PROCESOS.get(nombre, {}).get("reproduce")
    if not registro:
        raise SystemExit("Indica el registro a usar, ej: reproducir " + nombre + " OC-XXXX")

    nav, pag_o, pag_d = _abrir(p, headless=headless)
    print("\n=== REPRODUCIR: " + skill["titulo"] + "  (" + registro + ", datos nuevos) ===")
    ok, filas = _aplicar(pag_o, pag_d, skill, registro, verbose=True, lento=not headless)
    print("\n=== VALIDACION: ORIGEN (transformado) vs DESTINO ===")
    for nombre_c, esp, real, paso_ok in filas:
        print("   [" + ("OK" if paso_ok else "XX") + "] " + nombre_c.ljust(18) +
              " esperado=" + str(esp) + "  destino=" + real)
    print("\n" + ("RESULTADO: todo coincide" if ok else "RESULTADO: hay diferencias"))
    if pausar:
        input("\nENTER para cerrar...")
    nav.close()
    return ok


def lote(p, nombre, registros=None, headless=False, pausar=True):
    """ESCALABILIDAD: aprende UNA vez, ejecuta MUCHAS. Reproduce el mismo skill
    sobre varios registros seguidos y muestra un resumen."""
    skill = _cargar_skill(nombre)
    if not registros:
        registros = PROCESOS.get(nombre, {}).get("registros") or [PROCESOS[nombre]["reproduce"]]

    nav, pag_o, _tmp = _abrir(p, headless=headless)
    _tmp.close()
    print("\n=== LOTE: " + skill["titulo"] + " ===")
    print("Aprendido con 1 demostracion. Ejecutando " + str(len(registros)) + " registros en serie...\n")
    t0 = time.time()
    resultados = []
    for r in registros:
        ctx = nav.new_context()
        pag_d = ctx.new_page()
        ok, _ = _aplicar(pag_o, pag_d, skill, r, verbose=False, lento=not headless)
        resultados.append((r, ok))
        print("   [" + ("OK" if ok else "XX") + "]  " + r)
        if not headless:
            pag_d.wait_for_timeout(400)
        ctx.close()
    dt = time.time() - t0
    bien = sum(1 for _, ok in resultados if ok)
    print("\n=== RESUMEN DE ESCALABILIDAD ===")
    print("   " + str(bien) + "/" + str(len(resultados)) + " registros procesados correctamente")
    print("   Tiempo total: " + ("%.1f" % dt) + " s  (" + ("%.1f" % (dt / max(len(resultados), 1))) + " s por registro)")
    print("   1 demostracion humana  ->  " + str(len(resultados)) + " ejecuciones automaticas")
    if pausar:
        input("\nENTER para cerrar...")
    nav.close()
    return bien == len(resultados)


def listar():
    if not os.path.isdir(CARPETA_SKILLS):
        print("No hay skills grabados. Empieza con: python agente_universal.py grabar ordenes")
        return
    archivos = [f for f in os.listdir(CARPETA_SKILLS) if f.endswith(".json")]
    if not archivos:
        print("No hay skills grabados. Empieza con: python agente_universal.py grabar ordenes")
        return
    print("Skills grabados por el agente:")
    for a in sorted(archivos):
        ruta = os.path.join(CARPETA_SKILLS, a)
        with open(ruta, encoding="utf-8") as f:
            s = json.load(f)
        import datetime
        ts = os.path.getmtime(ruta)
        fecha = datetime.datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M")
        print("   " + s["nombre"].ljust(20) + s["titulo"][:40].ljust(42) +
              str(len(s["pasos"])) + " pasos  grabado " + fecha)


def limpiar(nombre=None):
    """Elimina skills grabados. Sin argumento elimina todos (pide confirmacion)."""
    if not os.path.isdir(CARPETA_SKILLS):
        print("No hay nada que limpiar (la carpeta skills/ no existe).")
        return
    if nombre:
        ruta = os.path.join(CARPETA_SKILLS, nombre + ".json")
        if not os.path.exists(ruta):
            print("No existe el skill '" + nombre + "'.")
            return
        os.remove(ruta)
        print("Skill '" + nombre + "' eliminado. El agente ya no recuerda ese proceso.")
        return
    archivos = [f for f in os.listdir(CARPETA_SKILLS) if f.endswith(".json")]
    if not archivos:
        print("No hay skills que limpiar.")
        return
    print("Se van a eliminar " + str(len(archivos)) + " skill(s): " +
          ", ".join(f.replace(".json", "") for f in archivos))
    resp = input("Confirma escribiendo 'si': ").strip().lower()
    if resp == "si":
        for f in archivos:
            os.remove(os.path.join(CARPETA_SKILLS, f))
        print("Todos los skills eliminados. El agente empieza desde cero.")
    else:
        print("Cancelado.")



def main():
    from playwright.sync_api import sync_playwright
    headless = "--headless" in sys.argv
    web_mode = "--web-mode" in sys.argv
    pausar = not web_mode
    # Filtra flags y el valor que sigue a --web-mode (el run_id), dejando
    # solo los argumentos posicionales (modo, proceso, registro...).
    args = []
    saltar = False
    for a in sys.argv[1:]:
        if saltar:
            saltar = False
            continue
        if a == "--headless":
            continue
        if a == "--web-mode":
            saltar = True
            continue
        args.append(a)
    modo = args[0] if args else ""

    # Comandos que no necesitan servidores ni navegador
    if modo == "skills":
        listar(); return
    if modo == "limpiar":
        limpiar(args[1] if len(args) > 1 else None); return

    iniciar_servidores()
    with sync_playwright() as p:
        if modo == "grabar":
            grabar(p, args[1] if len(args) > 1 else "ordenes")
        elif modo == "reproducir":
            reproducir(p, args[1] if len(args) > 1 else "ordenes",
                       args[2] if len(args) > 2 else None, headless=headless, pausar=pausar)
        elif modo == "lote":
            registros = args[2:] if len(args) > 2 else None
            lote(p, args[1] if len(args) > 1 else "ordenes", registros, headless=headless, pausar=pausar)
        else:
            print("\nUso:\n"" python agente_universal.py grabar <proceso>\n"" python agente_universal.py reproducir <proceso> <registro>\n"" python agente_universal.py lote <proceso> [registros...]\n"" python agente_universal.py skills\n""\nProcesos: " + ", ".join(PROCESOS.keys()))


if __name__ == "__main__":
    main()
