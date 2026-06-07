"""
CASO SUPREMO — Comprador inteligente (razonamiento real con Gemini)
===================================================================
El agente entra a saucedemo.com, lee el catalogo en vivo, y GEMINI DECIDE
que comprar segun un objetivo en lenguaje natural. Ejecuta la compra completa
(login -> catalogo -> carrito -> checkout -> validacion) de forma autonoma.

NO hay heuristica. NO hay hardcoding. Si no hay API key, el agente no puede
decidir y lo dice claramente. Eso es correcto: el reto requiere IA real.

USO:
    python caso_supremo.py "compra los 2 productos mas baratos"
    python caso_supremo.py "compra todo lo que cueste menos de 15 dolares"
    python caso_supremo.py "compra el producto mas caro"

    # Prueba del flujo de navegacion con tienda local (aun necesitas key):
    python caso_supremo.py --local "compra el mas barato"
"""
import os, re, sys, json, time, threading, functools
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GEMINI_API_KEY = ""  # <-- key aqui
GEMINI_MODELO  = "gemini-2.5-flash"
# Cuando el dashboard web lanza este script como subproceso exporta AOS_WEB=1.
# En ese caso no debemos bloquear con input() (no hay stdin interactivo): el
# proceso debe terminar solo para que el servidor emita el evento "done".
WEB_MODE = os.environ.get("AOS_WEB") == "1"
URL_REAL  = "https://www.saucedemo.com"
URL_LOCAL = "http://localhost:8090"
USUARIO   = "standard_user"
PASSWORD  = "secret_sauce"


def decidir_compras(catalogo, objetivo):
    """Gemini lee el catalogo en vivo y decide que comprar. Sin fallback."""
    key = GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise SystemExit(
            "Necesitas una GEMINI_API_KEY para que el agente pueda razonar.\n"
            "Pegala en GEMINI_API_KEY al inicio del archivo, o exporta la variable.\n"
            "La consigues gratis en https://aistudio.google.com/app/apikey"
        )
    try:
        from dotenv import load_dotenv; load_dotenv()
        key = GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY", key)
    except Exception:
        pass
    from google import genai
    from google.genai import types
    cli = genai.Client(api_key=key)
    prompt = (
        "Eres un agente de compras. Catalogo leido en vivo:\n"
        + json.dumps(catalogo, ensure_ascii=False, indent=2) +
        "\n\nObjetivo: \"" + objetivo + "\"\n\n"
        "Decide que productos comprar para cumplir el objetivo, razonando sobre "
        "precios y cantidades. Devuelve SOLO JSON: "
        "{\"productos\": [\"nombre exacto como aparece en el catalogo\", ...], "
        "\"razon\": \"explicacion breve\"}"
    )
    r = cli.models.generate_content(
        model=GEMINI_MODELO, contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0),
    )
    txt = (r.text or "").strip()
    if txt.startswith("```"): txt = txt.strip("`"); txt = txt[txt.find("{"):txt.rfind("}")+1]
    data = json.loads(txt)
    nombres = {c["nombre"] for c in catalogo}
    elegidos = [n for n in data.get("productos", []) if n in nombres]
    return elegidos, data.get("razon", "")


def correr(objetivo, base_url, headless=False):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        nav = p.chromium.launch(headless=headless)
        pag = nav.new_context().new_page()

        print("\n=== CASO SUPREMO: comprador inteligente ===")
        print("Objetivo: \"" + objetivo + "\"\n")
        pag.goto(base_url + "/")
        pag.fill('[data-test="username"]', USUARIO)
        pag.fill('[data-test="password"]', PASSWORD)
        pag.click('[data-test="login-button"]')
        pag.wait_for_selector(".inventory_item")
        print("Sesion iniciada. Leyendo catalogo en vivo...")

        cards = pag.locator(".inventory_item")
        catalogo = []
        for i in range(cards.count()):
            c = cards.nth(i)
            nombre = c.locator(".inventory_item_name").inner_text().strip()
            precio_txt = c.locator(".inventory_item_price").inner_text().strip()
            precio = float(re.sub(r"[^0-9.]", "", precio_txt) or 0)
            catalogo.append({"nombre": nombre, "precio": precio, "precio_txt": precio_txt})
        print("Catalogo (ordenado por precio):")
        for c in sorted(catalogo, key=lambda x: x["precio"]):
            print("   " + c["precio_txt"].rjust(8) + "  " + c["nombre"])

        elegidos, razon = decidir_compras(catalogo, objetivo)
        print("\n>>> DECISION DEL AGENTE: " + (", ".join(elegidos) if elegidos else "(ninguno)"))
        print(">>> Razon: " + razon + "\n")
        if not elegidos:
            print("El agente no eligio productos para este objetivo.")
            if not headless and not WEB_MODE: input("ENTER para cerrar...")
            nav.close(); return False

        for i in range(cards.count()):
            c = cards.nth(i)
            nombre = c.locator(".inventory_item_name").inner_text().strip()
            if nombre in elegidos:
                c.locator("button").first.click()
                print("   + agregado: " + nombre)
                pag.wait_for_timeout(150 if not headless else 0)

        pag.click('[data-test="shopping-cart-link"]')
        pag.wait_for_selector(".cart_item")
        en_carrito = [pag.locator(".cart_item .inventory_item_name").nth(i).inner_text().strip()
                      for i in range(pag.locator(".cart_item").count())]
        coincide = set(en_carrito) == set(elegidos)
        print("Carrito: " + ", ".join(en_carrito))
        print("Coincide con la decision: " + ("SI" if coincide else "NO"))

        pag.click('[data-test="checkout"]')
        pag.wait_for_selector('[data-test="firstName"]')
        pag.fill('[data-test="firstName"]', "Agente")
        pag.fill('[data-test="lastName"]', "AOS")
        pag.fill('[data-test="postalCode"]', "64000")
        pag.click('[data-test="continue"]')
        pag.wait_for_selector('[data-test="finish"]')
        pag.click('[data-test="finish"]')
        pag.wait_for_selector('[data-test="complete-header"]')
        header = pag.text_content('[data-test="complete-header"]').strip()

        ok = coincide and ("Thank you" in header or "Gracias" in header)
        print("\n=== VALIDACION ===")
        print("   Compra completada: " + header)
        print("   Items correctos:  " + ("SI" if coincide else "NO"))
        print("\n" + ("RESULTADO: el agente razono y compro correctamente" if ok
                      else "RESULTADO: hay diferencias, revisa arriba"))
        if not headless and not WEB_MODE: input("\nENTER para cerrar...")
        nav.close(); return ok



# ======== MODO 2: OBSERVAR Y REPLICAR (sin Gemini, pura copia) ========
# El agente graba lo que hace el usuario y lo replica exacto.
# A diferencia del caso supremo, aqui no hay razonamiento: es aprendizaje
# por observacion pura — copia el comportamiento demostrado.

ARCHIVO_SESION = "sesion_grabada.json"

# Inyectado en CADA pagina del navegador. Graba carrito y checkout
# en localStorage para que persista entre navegaciones (paginas distintas).
_INIT_SCRIPT = """
(function() {
    var KEY = '__agent_session';
    var sess = JSON.parse(localStorage.getItem(KEY) || '{"cart":[],"checkout":{}}');
    window.__session = sess;

    document.addEventListener('click', function(e) {
        var btn = e.target.closest('button');
        if (!btn) return;
        var item = btn.closest('.inventory_item');
        if (!item) return;
        var el = item.querySelector('.inventory_item_name');
        if (!el) return;
        var name = el.textContent.trim();
        var txt = btn.textContent.trim().toLowerCase();
        if (txt.indexOf('add') >= 0 || txt.indexOf('agregar') >= 0) {
            if (sess.cart.indexOf(name) < 0) sess.cart.push(name);
        } else {
            sess.cart = sess.cart.filter(function(n) { return n !== name; });
        }
        localStorage.setItem(KEY, JSON.stringify(sess));
        console.log('[GRABANDO] carrito: ' + sess.cart.join(' | '));
    }, true);

    function bindCheckout() {
        ['firstName', 'lastName', 'postalCode'].forEach(function(field) {
            var el = document.querySelector('[data-test="' + field + '"]');
            if (!el || el.__agentBound) return;
            el.__agentBound = true;
            el.addEventListener('change', function() {
                sess.checkout[field] = el.value;
                localStorage.setItem(KEY, JSON.stringify(sess));
                console.log('[GRABANDO] checkout.' + field + ' = ' + el.value);
            });
        });
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bindCheckout);
    } else {
        bindCheckout();
    }
})();
"""


def grabar_sesion(base_url, headless=False):
    """Observa lo que hace el usuario y graba la sesion en disco."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        nav = p.chromium.launch(headless=headless)
        # Contexto nuevo = localStorage vacio, sin residuos de sesiones previas
        ctx = nav.new_context()
        ctx.add_init_script(_INIT_SCRIPT)
        pag = ctx.new_page()
        pag.on("console", lambda m: print("   " + m.text)
               if m.text.startswith("[GRABANDO]") else None)

        print("\n=== GRABANDO SESION DE COMPRAS ===")
        print("Realiza tu compra normalmente en el navegador.")
        print("El agente graba cada producto que agregas y los datos del checkout.")
        print("Cuando veas la confirmacion final, el agente termina automaticamente.\n")

        pag.goto(base_url + "/")
        pag.fill('[data-test="username"]', USUARIO)
        pag.fill('[data-test="password"]', PASSWORD)
        pag.click('[data-test="login-button"]')
        pag.wait_for_selector(".inventory_item")
        print("Listo, ya puedes comprar. El agente esta observando...\n")

        pag.wait_for_selector('[data-test="complete-header"]', timeout=120000)
        sesion = pag.evaluate("JSON.parse(localStorage.getItem('__agent_session') || '{}')")
        nav.close()

    import json as _j
    cart = sesion.get("cart", [])
    checkout = sesion.get("checkout", {})
    if not cart:
        print("No se detecto ningun producto. Intenta de nuevo.")
        return
    with open(ARCHIVO_SESION, "w", encoding="utf-8") as f:
        _j.dump({"productos": cart, "checkout": checkout}, f, ensure_ascii=False, indent=2)

    print("\n=== SESION GRABADA ===")
    print("Productos:  " + ", ".join(cart))
    print("Checkout:   " + str(checkout))
    print("\nGuardado en " + ARCHIVO_SESION)
    print("Ahora corre:  python caso_supremo.py replicar")


def replicar_sesion(base_url, headless=False):
    """Replica exactamente la sesion grabada, sin ninguna intervencion humana."""
    import json as _j, os as _o
    if not _o.path.exists(ARCHIVO_SESION):
        raise SystemExit("No hay sesion grabada. Primero corre:\n"
                         "  python caso_supremo.py grabar")
    with open(ARCHIVO_SESION, encoding="utf-8") as f:
        sesion = _j.load(f)
    productos = sesion.get("productos", [])
    checkout = sesion.get("checkout", {})

    print("\n=== REPLICANDO SESION (sin intervencion humana) ===")
    print("Productos grabados: " + ", ".join(productos))
    print("Checkout grabado:   " + str(checkout) + "\n")

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        nav = p.chromium.launch(headless=headless)
        pag = nav.new_context().new_page()

        pag.goto(base_url + "/")
        pag.fill('[data-test="username"]', USUARIO)
        pag.fill('[data-test="password"]', PASSWORD)
        pag.click('[data-test="login-button"]')
        pag.wait_for_selector(".inventory_item")

        cards = pag.locator(".inventory_item")
        for i in range(cards.count()):
            c = cards.nth(i)
            nombre = c.locator(".inventory_item_name").inner_text().strip()
            if nombre in productos:
                c.locator("button").first.click()
                print("   + agregado: " + nombre)
                pag.wait_for_timeout(200 if not headless else 0)

        pag.click('[data-test="shopping-cart-link"]')
        pag.wait_for_selector(".cart_item")
        en_carrito = [
            pag.locator(".cart_item .inventory_item_name").nth(i).inner_text().strip()
            for i in range(pag.locator(".cart_item").count())
        ]
        coincide = set(en_carrito) == set(productos)
        print("Carrito replicado: " + ", ".join(en_carrito))

        pag.click('[data-test="checkout"]')
        pag.wait_for_selector('[data-test="firstName"]')
        pag.fill('[data-test="firstName"]', checkout.get("firstName", "Agente"))
        pag.fill('[data-test="lastName"]', checkout.get("lastName", "AOS"))
        pag.fill('[data-test="postalCode"]', checkout.get("postalCode", "64000"))
        pag.click('[data-test="continue"]')
        pag.wait_for_selector('[data-test="finish"]')
        pag.click('[data-test="finish"]')
        pag.wait_for_selector('[data-test="complete-header"]')
        header = pag.text_content('[data-test="complete-header"]').strip()

        ok = coincide and ("Thank you" in header or "Gracias" in header)
        print("\n=== VALIDACION ===")
        print("   Compra completada: " + header)
        print("   Replica exacta:    " + ("SI" if coincide else "NO"))
        print("\n" + ("RESULTADO: sesion replicada correctamente" if ok
                      else "RESULTADO: hay diferencias"))
        if not headless and not WEB_MODE:
            input("\nENTER para cerrar...")
        nav.close()
        return ok


# ---- Tienda local espejo de saucedemo (para probar el flujo sin internet) ----
_PRODS = [("Sauce Labs Backpack","29.99"),("Sauce Labs Bike Light","9.99"),
          ("Sauce Labs Bolt T-Shirt","15.99"),("Sauce Labs Fleece Jacket","49.99"),
          ("Sauce Labs Onesie","7.99"),("Test.allTheThings() T-Shirt (Red)","15.99")]

def _mock():
    cards = "".join('<div class="inventory_item"><div class="inventory_item_name">'+n+'</div>'+
                    '<div class="inventory_item_price">$'+p+'</div>'+
                    '<button onclick="add(this,\''+n.replace("\'","")+"\'"+')">Add to cart</button></div>'
                    for n,p in _PRODS)
    login  = "<meta charset='utf-8'><input data-test='username'><input data-test='password' type='password'><button data-test='login-button' onclick=\"if(document.querySelector('[data-test=username]').value){location.href='inventory.html'}\">Login</button>"
    inv = ("<meta charset=\'utf-8\'><a data-test=\'shopping-cart-link\' href=\'cart.html\'>Carrito(<span id=\'b\'>0</span>)</a><hr>" + cards +
             "<script>function getCart(){return JSON.parse(localStorage.getItem(\'cart\')||\'[]\')} "
             "function saveCart(c){localStorage.setItem(\'cart\',JSON.stringify(c));document.getElementById(\'b\').textContent=c.length} "
             "function add(btn,n){var c=getCart();if(c.indexOf(n)<0){c.push(n);saveCart(c);btn.textContent=\'Remove\'}else{c=c.filter(function(x){return x!=n});saveCart(c);btn.textContent=\'Add to cart\'}} "
             "saveCart(getCart());</script>")
    cart = ("<meta charset=\'utf-8\'><div id=\'items\'></div>"
            "<button data-test=\'checkout\' onclick=\"location.href=\'step1.html\'\">Checkout</button>"
            "<script>var c=JSON.parse(localStorage.getItem(\'cart\')||\'[]\');"
            "document.getElementById(\'items\').innerHTML=c.map(function(n){"
            "return \"<div class=\'cart_item\'><div class=\'inventory_item_name\'>\" + n + \"</div></div>\";"
            "}).join(\'\');</script>")
    step1  = "<meta charset='utf-8'><input data-test='firstName'><input data-test='lastName'><input data-test='postalCode'><button data-test='continue' onclick=\"location.href='step2.html'\">Continue</button>"
    step2  = "<meta charset='utf-8'><button data-test='finish' onclick=\"location.href='complete.html'\">Finish</button>"
    compl  = "<meta charset='utf-8'><h2 data-test='complete-header'>Thank you for your order!</h2>"
    return {"/":login,"/index.html":login,"/inventory.html":inv,"/cart.html":cart,
            "/step1.html":step1,"/step2.html":step2,"/complete.html":compl}

def _servir_local():
    rutas = _mock()
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            html = rutas.get(self.path.split("?")[0])
            if html is None: self.send_error(404); return
            data = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type","text/html;charset=utf-8")
            self.send_header("Content-Length",str(len(data)))
            self.end_headers(); self.wfile.write(data)
        def log_message(self,*a): pass
    s = ThreadingHTTPServer(("127.0.0.1",8090),H)
    threading.Thread(target=s.serve_forever,daemon=True).start()
    time.sleep(0.4)

def main():
    args = sys.argv[1:]
    local    = "--local"    in args
    headless = "--headless" in args
    base     = URL_LOCAL if local else URL_REAL
    partes   = [a for a in args if not a.startswith("--")]
    modo     = partes[0] if partes else ""

    if local:
        _servir_local()

    if modo == "grabar":
        # Modo 2a: observar al usuario y grabar la sesion
        grabar_sesion(base, headless)

    elif modo == "replicar":
        # Modo 2b: replicar exactamente la sesion grabada
        replicar_sesion(base, headless)

    elif modo:
        # Modo 1: razonamiento con Gemini (objetivo en lenguaje natural)
        objetivo = " ".join(partes)
        correr(objetivo, base, headless)

    else:
        print("\nUso:")
        print("  Razonamiento (Gemini decide):  python caso_supremo.py \"objetivo\"")
        print("  Grabar sesion de usuario:      python caso_supremo.py grabar")
        print("  Replicar sesion grabada:       python caso_supremo.py replicar")
        print("  Agregar --local para tienda sin internet\n")

if __name__ == "__main__":
    main()

