from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import ezdxf
from ezdxf import DXFStructureError
import tempfile
import uuid
import os
from pathlib import Path
from typing import List

app = FastAPI(title="DWG Extractor", version="1.0.0")

# CORS si vas a consumir desde un frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Ajustá según tus necesidades
    allow_methods=["*"],
    allow_headers=["*"],
)


class ExtractedElement(BaseModel):
    kind: str
    layer: str
    data: dict


class ExtractionResponse(BaseModel):
    file_name: str
    count: int
    elements: List[ExtractedElement]


@app.get("/health")
async def health_check():
    """Health check para que Cloudflare sepa que estás vivo"""
    return {"status": "ok", "service": "dwg-extractor"}


@app.post("/extract", response_model=ExtractionResponse)
async def extract_dwg(file: UploadFile = File(...)):
    # Validación de tipo de archivo
    if not file.filename.lower().endswith((".dwg", ".dxf")):
        raise HTTPException(400, "Solo se aceptan archivos DWG o DXF")

    temp_path = None
    try:
        # Usar tempfile.NamedTemporaryFile es más seguro
        with tempfile.NamedTemporaryFile(delete=False, suffix=".dwg") as tmp:
            content = await file.read()
            tmp.write(content)
            temp_path = tmp.name

        # Load con manejo de errores
        try:
            doc = ezdxf.readfile(temp_path)
        except DXFStructureError as e:
            raise HTTPException(400, f"Archivo DWG/DXF corrupto: {str(e)}")

        msp = doc.modelspace()
        results = []

        for entity in msp:
            kind = entity.dxftype()
            layer = entity.dxf.layer
            data = {}

            if kind == "LINE":
                data = {
                    "start": list(entity.dxf.start),
                    "end": list(entity.dxf.end),
                    "length": round(entity.dxf.start.distance(entity.dxf.end), 4),
                }
            elif kind == "CIRCLE":
                data = {
                    "center": list(entity.dxf.center),
                    "radius": round(entity.dxf.radius, 4),
                }
            elif kind == "TEXT":
                data = {
                    "text": entity.dxf.text,
                    "insert": list(entity.dxf.insert),
                    "height": round(entity.dxf.height, 4),
                }
            elif kind == "LWPOLYLINE":  # Polylines son re comunes en DWG
                points = [list(p) for p in entity.get_points()]
                data = {"points": points, "closed": entity.closed}
            else:
                continue

            results.append(ExtractedElement(kind=kind, layer=layer, data=data))

        return ExtractionResponse(
            file_name=file.filename, count=len(results), elements=results
        )

    finally:
        # Limpieza siempre
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
