"""SportTV - Web profesional para distribuir listas M3U8 diarias.

El administrador sube cada dia su lista .m3u8 (protegido por contrasena) y
la web la muestra publicamente con un boton de descarga, identificada por fecha.
"""

import os
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

BASE = Path(__file__).resolve().parent
LISTS_DIR = BASE / "lists"
LISTS_DIR.mkdir(exist_ok=True)
INDEX = LISTS_DIR / "index.json"
STATIC = BASE / "static"

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
SECRET = hashlib.sha256(ADMIN_PASSWORD.encode()).hexdigest()

app = FastAPI(title="SportTV")
app.mount("/assets", StaticFiles(directory=STATIC), name="assets")


def load_index():
    if INDEX.exists():
        try:
            return json.loads(INDEX.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def save_index(data):
    INDEX.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
        "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def fmt_date(d):
    try:
        y, m, dd = map(int, d.split("-"))
        return f"{dd} de {MESES[m - 1]} de {y}"
    except Exception:
        return d


def auth_ok(request: Request):
    return request.cookies.get("sp_session") == SECRET


@app.get("/")
def home():
    return FileResponse(STATIC / "index.html")


@app.get("/admin")
def admin():
    return FileResponse(STATIC / "admin.html")


@app.get("/api/lists")
def api_lists():
    data = load_index()
    data.sort(key=lambda x: x.get("date", ""), reverse=True)
    return {"count": len(data), "lists": data}


@app.post("/api/login")
def login(password: str = Form(...)):
    if password == ADMIN_PASSWORD:
        r = JSONResponse({"ok": True})
        r.set_cookie("sp_session", SECRET, httponly=True, samesite="lax")
        return r
    raise HTTPException(status_code=401, detail="contrasena incorrecta")


@app.post("/api/upload")
async def upload(
    request: Request,
    file: UploadFile = File(...),
    date: str = Form(None),
    label: str = Form(""),
    password: str = Form(""),
):
    if not auth_ok(request) and password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="no autorizado")
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    if not all(c.isdigit() or c == "-" for c in date) or len(date) != 10:
        raise HTTPException(status_code=400, detail="fecha invalida (use AAAA-MM-DD)")
    content = await file.read()
    filename = f"{date}.m3u8"
    (LISTS_DIR / filename).write_bytes(content)
    entry = {
        "date": date,
        "label": label or fmt_date(date),
        "filename": filename,
        "size": len(content),
        "uploadedAt": datetime.now(timezone.utc).isoformat(),
    }
    idx = [e for e in load_index() if e["date"] != date]
    idx.append(entry)
    save_index(idx)
    return {"ok": True, "entry": entry}


@app.post("/api/delete")
async def delete(request: Request, date: str = Form(...), password: str = Form("")):
    if not auth_ok(request) and password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="no autorizado")
    idx = load_index()
    entry = next((e for e in idx if e["date"] == date), None)
    if not entry:
        raise HTTPException(status_code=404, detail="no encontrado")
    f = LISTS_DIR / entry["filename"]
    if f.exists():
        f.unlink()
    save_index([e for e in idx if e["date"] != date])
    return {"ok": True}


@app.get("/lists/{filename}")
def download(filename: str):
    if not filename.endswith(".m3u8") or ".." in filename or "/" in filename:
        raise HTTPException(status_code=400, detail="archivo invalido")
    path = LISTS_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="no encontrado")
    return FileResponse(
        path,
        media_type="application/vnd.apple.mpegurl",
        filename=filename,
    )
