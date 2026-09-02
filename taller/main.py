"""Pantalla de fichas + chat de prueba. Puerto 8010, no es WhatsApp."""

from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from taller import chat, excel, knowledge

_STATIC = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Taller IAHAF — fichas")
app.mount("/assets", StaticFiles(directory=_STATIC), name="assets")


class PiezaIn(BaseModel):
    nombre: str = ""
    marca: str = ""
    lado: str = ""
    codigo: str = ""
    nota: str = ""


class FichaIn(BaseModel):
    id: str = ""
    marca: str = ""
    modelo: str = ""
    motor: str = ""
    anio: str = ""
    conjunto: str = ""
    notas: str = ""
    venta: str = ""
    piezas: list[PiezaIn] = Field(default_factory=list)


class ChatIn(BaseModel):
    message: str = ""
    history: list[dict] = Field(default_factory=list)


@app.get("/")
async def home():
    return FileResponse(_STATIC / "index.html")


@app.get("/api/fichas")
async def list_fichas():
    return {"fichas": knowledge.load_all()}


@app.post("/api/fichas")
async def save_ficha(body: FichaIn):
    if not body.modelo.strip() and not body.conjunto.strip():
        raise HTTPException(400, "Hace falta modelo o conjunto")
    saved = knowledge.upsert(body.model_dump())
    return {"ficha": saved}


@app.delete("/api/fichas/{ficha_id}")
async def remove_ficha(ficha_id: str):
    if not knowledge.delete(ficha_id):
        raise HTTPException(404, "No está esa ficha")
    return {"ok": True}


@app.get("/api/fichas.xlsx")
async def download_excel():
    data = excel.export_bytes()
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="fichas-taller.xlsx"'},
    )


@app.post("/api/fichas/excel")
async def upload_excel(file: UploadFile = File(...)):
    name = (file.filename or "").lower()
    if not name.endswith(".xlsx"):
        raise HTTPException(400, "Tiene que ser un Excel .xlsx")
    raw = await file.read()
    if len(raw) > 2_500_000:
        raise HTTPException(400, "El archivo es muy grande (máximo 2,5 MB)")
    try:
        return excel.import_bytes(raw)
    except excel.ExcelError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/chat")
async def chat_turno(body: ChatIn):
    text = (body.message or "").strip()
    if not text:
        raise HTTPException(400, "Escribí una pregunta")
    return await chat.answer(text, body.history[-8:])
