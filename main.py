from fastapi import FastAPI, File, UploadFile, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import ezdxf
from ezdxf import DXFStructureError
import tempfile
import os
from typing import Optional
import logging
import magic  # pip install python-magic

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="DWG Extractor", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "dwg-extractor"}


def detect_file_type(file_path: str) -> dict:
    """Detecta el tipo de archivo y sus primeros bytes"""
    with open(file_path, "rb") as f:
        header = f.read(100)

    # Los archivos DXF empiezan con "0\r\nSECTION" o similar (texto)
    # Los archivos DWG empiezan con "AC1" seguido de la versión

    is_text = all(b < 128 for b in header[:50] if b != 0)

    return {
        "first_bytes": header[:50].hex(),
        "first_chars": header[:50].decode("ascii", errors="ignore"),
        "likely_type": "DXF" if is_text else "DWG",
        "starts_with_ac": header.startswith(b"AC"),
    }


@app.post("/extract")
async def extract_dwg(request: Request, file: Optional[UploadFile] = File(None)):
    logger.info(f"Content-Type: {request.headers.get('content-type')}")

    if not file:
        body = await request.body()
        logger.error(f"No file received. Body length: {len(body)}")
        raise HTTPException(400, "No se recibió ningún archivo")

    logger.info(f"File received: {file.filename}, content_type: {file.content_type}")

    if not file.filename:
        raise HTTPException(400, "El archivo debe tener un nombre")

    temp_path = None
    try:
        # Guardar archivo temporal
        with tempfile.NamedTemporaryFile(delete=False, suffix=".dwg") as tmp:
            content = await file.read()
            logger.info(f"Read {len(content)} bytes")

            if len(content) == 0:
                raise HTTPException(400, "El archivo está vacío")

            tmp.write(content)
            temp_path = tmp.name

        # Detectar tipo de archivo
        file_info = detect_file_type(temp_path)
        logger.info(f"File info: {file_info}")

        # Intentar leer con ezdxf
        try:
            # ezdxf puede leer algunos DWG directamente
            doc = ezdxf.readfile(temp_path)
        except IOError as e:
            # Si falla, dar info útil
            raise HTTPException(
                422,
                detail={
                    "error": "No se pudo leer el archivo",
                    "message": str(e),
                    "file_info": file_info,
                    "suggestion": "Convierte el archivo a DXF en AutoCAD o usa 'Guardar como' → DXF",
                },
            )
        except DXFStructureError as e:
            raise HTTPException(400, f"Archivo DXF corrupto: {str(e)}")

        msp = doc.modelspace()
        results = []

        for entity in msp:
            kind = entity.dxftype()
            layer = entity.dxf.layer
            entity_data = {}

            try:
                if kind == "LINE":
                    entity_data = {
                        "start": list(entity.dxf.start),
                        "end": list(entity.dxf.end),
                        "length": round(entity.dxf.start.distance(entity.dxf.end), 4),
                    }
                elif kind == "CIRCLE":
                    entity_data = {
                        "center": list(entity.dxf.center),
                        "radius": round(entity.dxf.radius, 4),
                    }
                elif kind == "ARC":
                    entity_data = {
                        "center": list(entity.dxf.center),
                        "radius": round(entity.dxf.radius, 4),
                        "start_angle": entity.dxf.start_angle,
                        "end_angle": entity.dxf.end_angle,
                    }
                elif kind == "TEXT":
                    entity_data = {
                        "text": entity.dxf.text,
                        "insert": list(entity.dxf.insert),
                        "height": round(entity.dxf.height, 4),
                    }
                elif kind == "MTEXT":
                    entity_data = {
                        "text": entity.text,
                        "insert": list(entity.dxf.insert),
                    }
                elif kind == "LWPOLYLINE":
                    points = [list(p) for p in entity.get_points()]
                    entity_data = {"points": points, "closed": entity.closed}
                elif kind == "POLYLINE":
                    points = [list(v.dxf.location) for v in entity.vertices]
                    entity_data = {"points": points, "closed": entity.is_closed}
                else:
                    # Ignorar entidades no soportadas
                    continue

                results.append({"kind": kind, "layer": layer, "data": entity_data})
            except Exception as e:
                logger.warning(f"Error procesando entidad {kind}: {e}")
                continue

        return {
            "file_name": file.filename,
            "file_type": file_info.get("likely_type"),
            "count": len(results),
            "elements": results,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        raise HTTPException(500, f"Error interno: {str(e)}")
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except:
                pass


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8083, log_level="info")
