"""API de Partidos TV.

Sirve los partidos (iframe + imagen "vs" compuesta) a partir de matches.json.
Origen de datos (configurable por env):
  - MATCHES_FILE : ruta local a matches.json (para pruebas/uso local).
  - MATCHES_URL  : URL http(s) a matches.json (ej. GitHub Pages / raw).
  - GITHUB_TOKEN : si se define, se usa la API de GitHub para repos privados.

Endpoints:
  GET /                       -> health check
  GET /api/matches            -> lista de partidos (con vsImage)
  GET /api/match/{id}         -> un partido
  GET /vs/{id}.png            -> imagen "vs" generada (logos + VS)
"""

import os
import io
import json
import time
import base64
import threading
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from PIL import Image, ImageDraw, ImageFont

BASE_DIR = Path(__file__).resolve().parent
VS_DIR = BASE_DIR / "static" / "vs"
VS_DIR.mkdir(parents=True, exist_ok=True)

MATCHES_FILE = os.environ.get("MATCHES_FILE")
MATCHES_URL = os.environ.get("MATCHES_URL", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "danielgarciagonzalezarmenia-ai/partidos-tv")
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")
CACHE_TTL = int(os.environ.get("CACHE_TTL", "300"))

app = FastAPI(title="Partidos TV API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_cache = {"data": None, "ts": 0}
_lock = threading.Lock()


def _fetch_remote():
    if GITHUB_TOKEN:
        url = (f"https://api.github.com/repos/{GITHUB_REPO}/contents/matches.json"
               f"?ref={GITHUB_BRANCH}")
        headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
        }
        with httpx.Client(timeout=30) as c:
            r = c.get(url, headers=headers)
            r.raise_for_status()
            return json.loads(base64.b64decode(r.json()["content"]))
    with httpx.Client(timeout=30, follow_redirects=True) as c:
        r = c.get(MATCHES_URL)
        r.raise_for_status()
        return r.json()


def get_matches():
    now = time.time()
    if _cache["data"] is None or now - _cache["ts"] > CACHE_TTL:
        with _lock:
            if _cache["data"] is None or now - _cache["ts"] > CACHE_TTL:
                if MATCHES_FILE and os.path.exists(MATCHES_FILE):
                    with open(MATCHES_FILE, "r", encoding="utf-8") as f:
                        _cache["data"] = json.load(f)
                else:
                    _cache["data"] = _fetch_remote()
                _cache["ts"] = now
    return _cache["data"]


def _vs_path(mid):
    return VS_DIR / f"{mid}.png"


def _download(url, timeout=15):
    with httpx.Client(timeout=timeout, follow_redirects=True) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.content


def _fit_logo(img, size=200):
    img = img.convert("RGBA")
    img.thumbnail((size, size), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(img, ((size - img.width) // 2, (size - img.height) // 2), img)
    return canvas


def _make_vs_image(mid, home_url, away_url, home_name, away_name):
    W, H = 640, 360
    bg = Image.new("RGBA", (W, H), (14, 17, 22, 255))
    draw = ImageDraw.Draw(bg)
    try:
        font = ImageFont.truetype("arial.ttf", 90)
    except Exception:
        font = ImageFont.load_default()
    try:
        if home_url:
            home = _fit_logo(Image.open(io.BytesIO(_download(home_url))))
            bg.paste(home, (70, 90), home)
        if away_url:
            away = _fit_logo(Image.open(io.BytesIO(_download(away_url))))
            bg.paste(away, (W - 70 - 200, 90), away)
    except Exception:
        pass
    # texto VS al centro
    vs = "VS"
    try:
        bbox = draw.textbbox((0, 0), vs, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        tw, th = 90, 90
    draw.text(((W - tw) / 2, (H - th) / 2 - 10), vs, fill=(230, 230, 230, 255), font=font)
    # nombres abajo
    try:
        nfont = ImageFont.truetype("arial.ttf", 22)
    except Exception:
        nfont = ImageFont.load_default()
    hn = (home_name or "")[:18]
    an = (away_name or "")[:18]
    draw.text((70, 300), hn, fill=(180, 180, 180, 255), font=nfont)
    draw.text((W - 70 - draw.textlength(an, font=nfont), 300), an,
              fill=(180, 180, 180, 255), font=nfont)
    out = _vs_path(mid)
    bg.convert("RGB").save(out, "PNG")
    return out


@app.get("/")
def root():
    return {"status": "ok", "service": "partidos-tv-api"}


@app.get("/api/matches")
def api_matches():
    data = get_matches()
    matches = data.get("matches", [])
    out = []
    for m in matches:
        mm = dict(m)
        mid = m.get("id") or ""
        mm["vsImage"] = f"/vs/{mid}.png" if mid else None
        out.append(mm)
    return {"updated": data.get("updated"), "count": len(out), "matches": out}


@app.get("/api/match/{mid}")
def api_match(mid: str):
    data = get_matches()
    for m in data.get("matches", []):
        if (m.get("id") or "") == mid:
            mm = dict(m)
            mm["vsImage"] = f"/vs/{mid}.png"
            return mm
    raise HTTPException(status_code=404, detail="partido no encontrado")


@app.get("/vs/{mid}.png")
def vs_image(mid: str):
    path = _vs_path(mid)
    if not path.exists():
        data = get_matches()
        m = next((x for x in data.get("matches", []) if (x.get("id") or "") == mid), None)
        if not m:
            raise HTTPException(status_code=404, detail="partido no encontrado")
        _make_vs_image(
            mid,
            m.get("homeLogo"),
            m.get("awayLogo"),
            m.get("home"),
            m.get("away"),
        )
    return FileResponse(path)
