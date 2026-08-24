"""Scraper de partidos para Partidos TV.

Mecanismo (investigado):
  - Listado: POST https://api-gateway.top-parser.com/matches/get-many
      body: {"service":"live"|"prematch","excludeSportType":"polybet","limit":200,"hotsLimit":100}
      headers: x-external-partner-id, x-lang, x-user-location, content-type
    Devuelve items con id, slug, homeTeam, awayTeam, startAt, tournamentId.
    La URL del partido se construye como:
      https://1win.com/es/betting/match/sport/{slug}-{id}
  - Iframe: al abrir la página del partido y pulsar "Transmisión", 1win llama
    POST api-gateway.top-parser.com/broadcast/get-url -> {"result":{"url": "<iframe>"}}
    Ese endpoint exige la sesión de 1win (cookies), por eso el bot usa cookies.json.

Flujo del bot:
  1. Carga cookies (sesión de 1win).
  2. Lista los partidos vía matches/get-many (live y/o prematch).
  3. Por cada partido: abre la página, pulsa "Transmisión" y captura el iframe.
  4. Guarda matches.json.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
OUT_PATH = os.path.join(HERE, "..", "matches.json")

# Competiciones que NO son fútbol real (eSports/simulaciones/virtuales) o que
# no son "ligas grandes" (femeniles/juveniles). top-parser etiqueta las
# simulaciones como sport=football, así que se filtran por nombre.
FAKE_FOOTBALL_RE = re.compile(
    r"esports|e-sports|h2h|gg league|ehighlights|virtual|"
    r"penalty shootout|highlights|simulation|cyber|betball|"
    r"femenin|women|femenina|\bu19\b|\bu20\b|\bu21\b|\bu23\b|youth|sub[\s-]?\d",
    re.IGNORECASE,
)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
PARTNER_ID = "44ba10e5-7df2-47ab-a44d-dc93803c7a6e"
API = "https://api-gateway.top-parser.com"


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_cookies(config):
    path = config.get("cookies_file")
    if not path:
        return []
    full = path if os.path.isabs(path) else os.path.join(HERE, path)
    if not os.path.exists(full):
        print("! cookies_file no encontrado:", full)
        return []
    with open(full, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        return []
    allowed_same = {"Strict", "Lax", "None"}
    clean = []
    for c in data:
        c = dict(c)
        if c.get("sameSite") not in allowed_same:
            c.pop("sameSite", None)
        c.pop("hostOnly", None)
        c.pop("session", None)
        c.pop("storeId", None)
        clean.append(c)
    return clean


def get_listing_api(page, service, sport_id):
    """Devuelve la lista de partidos desde matches/get-many."""
    js = f"""async (service) => {{
      const h = {{
        'content-type':'application/json',
        'x-external-partner-id':'{PARTNER_ID}',
        'x-lang':'es-ES',
        'x-user-location':'co',
        'accept':'application/json'
      }};
      const body = JSON.stringify({{service, excludeSportType:'polybet', limit:200, hotsLimit:100, sportId:{sport_id}}});
      const r = await fetch('{API}/matches/get-many', {{method:'POST', headers:h, body}});
      const j = await r.json();
      return (j.result && j.result.items) || [];
    }}"""
    return page.evaluate(js, service)


def tournament_name(page, tid, cache):
    if tid in cache:
        return cache[tid]
    js = f"""async (id) => {{
      const h = {{'content-type':'application/json','x-external-partner-id':'{PARTNER_ID}','x-lang':'es-ES'}};
      try {{
        const r = await fetch('{API}/tournaments/get?tournamentId='+id+'&l=es-ES&p={PARTNER_ID}',{{headers:h}});
        const j = await r.json();
        return (j.result && j.result.name) || '';
      }} catch(e) {{ return ''; }}
    }}"""
    name = page.evaluate(js, tid) or ""
    cache[tid] = name
    return name


def get_iframe(page, match_url):
    """Pulsa Transmisión y captura la respuesta de broadcast/get-url."""
    page.goto(match_url, wait_until="domcontentloaded", timeout=60000)
    try:
        btn = page.get_by_text("Transmisión", exact=False).first
        btn.wait_for(state="visible", timeout=12000)
        page.wait_for_timeout(800)
        with page.expect_response(
            lambda r: "broadcast/get-url" in r.url, timeout=15000
        ) as resp_info:
            btn.click(timeout=10000)
        body = resp_info.value.json()
        url = (body.get("result") or {}).get("url")
        if url:
            return url
        print("  broadcast/get-url (sin url):", json.dumps(body)[:300])
    except Exception as e:
        print("  ! broadcast/get-url no capturado:", e)
    return None


def main():
    config = load_config()
    cookies = load_cookies(config)
    results = []
    tcache = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, locale="es-ES")
        if cookies:
            ctx.add_cookies(cookies)
        page = ctx.new_page()
        # Establecer origen 1win para poder llamar a la API vía fetch.
        page.goto("https://1win.com/es/betting/live",
                  wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        # Fuente de partidos: match_urls manuales o API de listado.
        items = []
        manual = config.get("match_urls") or []
        if manual:
            for u in manual:
                mid = re.search(r"(\d{6,})$", u.rstrip("/"))
                items.append({
                    "url": u,
                    "id": mid.group(1) if mid else "",
                    "slug": "",
                    "homeTeam": {"name": "?"},
                    "awayTeam": {"name": "?"},
                    "startAt": 0,
                    "tournamentId": None,
                })
        else:
            periods = config.get("periods") or ["live", "prematch"]
            sport_id = config.get("sport_id", 18)
            only_top = config.get("only_top_leagues", False)
            top_leagues = [str(k).lower() for k in (config.get("top_leagues") or [])]
            now = datetime.now(timezone.utc).timestamp()
            for svc in periods:
                print(f"Listando ({svc})...")
                for it in get_listing_api(page, svc, sport_id):
                    # Solo fútbol real (excluye eSports/simulaciones virtuales).
                    sp = it.get("sport") or {}
                    if sp.get("slug") != "football" or sp.get("isEsport"):
                        continue
                    # (El filtro de ligas grandes se aplica tras resolver el nombre
                    #  en la fase de procesamiento, para no abrir paginas innecesarias.)
                    # Para prematch, solo los próximos 48h (evita partidos lejanos).
                    if svc == "prematch":
                        sa = it.get("startAt") or 0
                        if sa <= now or sa > now + 48 * 3600:
                            continue
                    slug = it.get("slug") or ""
                    mid = it.get("id") or ""
                    items.append({
                        "url": f"https://1win.com/es/betting/match/sport/{slug}-{mid}",
                        "id": mid,
                        "slug": slug,
                        "homeTeam": it.get("homeTeam") or {"name": "?"},
                        "awayTeam": it.get("awayTeam") or {"name": "?"},
                        "startAt": it.get("startAt") or 0,
                        "tournamentId": it.get("tournamentId"),
                    })

        max_matches = config.get("max_matches")
        # Priorizar: live primero, luego prematch por hora de inicio (los mas
        # inminentes entran en el presupuesto antes del challenge de Cloudflare).
        items.sort(key=lambda it: (it.get("service") != "live", it.get("startAt") or 0))

        # Nota: no recortamos 'items' aqui para no perder grandes ligas; se
        # limita el resultado final a max_matches despues de filtrar.
        print(f"Total partidos a procesar: {len(items)}")
        seen = set()
        for it in items:
            url = it["url"]
            if url in seen:
                continue
            seen.add(url)
            try:
                # Resolver competicion y filtrar ANTES de abrir la pagina (ahorra tiempo).
                comp = tournament_name(page, it.get("tournamentId"), tcache) or "Otros"
                # Excluye eSports/simulaciones (top-parser las etiqueta como football).
                if FAKE_FOOTBALL_RE.search(comp):
                    continue
                # Solo ligas grandes (whitelist configurable).
                if only_top and not any(k in comp.lower() for k in top_leagues):
                    continue
                print("Procesando:", url)
                iframe = get_iframe(page, url)
                # Espaciar requests para no disparar el challenge de Cloudflare.
                page.wait_for_timeout(3000)
                if not iframe:
                    continue
                start_iso = (datetime.fromtimestamp(it["startAt"], timezone.utc).isoformat()
                             if it.get("startAt") else datetime.now(timezone.utc).isoformat())
                results.append({
                    "id": it.get("id", ""),
                    "home": (it.get("homeTeam") or {}).get("name", "?"),
                    "away": (it.get("awayTeam") or {}).get("name", "?"),
                    "homeLogo": (it.get("homeTeam") or {}).get("logo", {}).get("url"),
                    "awayLogo": (it.get("awayTeam") or {}).get("logo", {}).get("url"),
                    "competition": comp,
                    "startTime": start_iso,
                    "live": it.get("service") == "live",
                    "source": "1win",
                    "iframe": iframe,
                })
            except Exception as e:
                print("  ! error procesando", url, ":", str(e)[:120])
        browser.close()

    # Orden: live primero y luego por hora de inicio.
    results.sort(key=lambda m: (m.get("live") is not True, m.get("startTime") or ""))
    if max_matches:
        results = results[: int(max_matches)]

    out = {"updated": datetime.now(timezone.utc).isoformat(), "matches": results}
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"Guardado matches.json con {len(results)} partidos.")


if __name__ == "__main__":
    sys.exit(main())
