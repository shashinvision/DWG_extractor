from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import ezdxf
from ezdxf import DXFStructureError
import tempfile
import os
from typing import Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="DWG Extractor", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def detect_file_format(file_path: str) -> dict:
    """Detecta si el archivo es DXF o DWG"""
    with open(file_path, "rb") as f:
        header = f.read(100)

    # DXF es texto ASCII, DWG es binario
    try:
        text = header[:50].decode("ascii")
        is_dxf = "0\n" in text or "SECTION" in text or "HEADER" in text
    except:
        is_dxf = False

    is_dwg = header.startswith(b"AC")

    version = "Unknown"
    if is_dwg:
        version_code = header[0:6].decode("ascii", errors="ignore")
        versions = {
            "AC1032": "AutoCAD 2018-2021",
            "AC1027": "AutoCAD 2013-2017",
            "AC1024": "AutoCAD 2010-2012",
            "AC1021": "AutoCAD 2007-2009",
            "AC1018": "AutoCAD 2004-2006",
        }
        version = versions.get(version_code, version_code)

    return {
        "is_dxf": is_dxf,
        "is_dwg": is_dwg,
        "version": version,
        "file_size": os.path.getsize(file_path),
    }


@app.get("/")
async def root():
    return {
        "service": "DWG/DXF Extractor API",
        "version": "1.0.0",
        "endpoints": {"health": "/health", "extract": "/extract (POST)"},
        "note": "Este servicio solo acepta archivos DXF. Si tienes un DWG, conviértelo primero.",
        "how_to_convert": {
            "method_1": "En AutoCAD: File → Save As → DXF (ASCII format)",
            "method_2": "Usar LibreCAD (gratis): https://librecad.org",
            "method_3": "Convertidor online: https://www.zamzar.com/convert/dwg-to-dxf/",
        },
    }


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "service": "dwg-extractor",
        "accepts": ["DXF (ASCII)", "DXF (Binary)"],
        "note": "DWG files must be converted to DXF first",
    }


@app.post("/extract")
async def extract_dwg(file: Optional[UploadFile] = File(None)):
    logger.info(f"=== New Request ===")

    if not file:
        raise HTTPException(400, "No se recibió ningún archivo")

    logger.info(f"📄 File: {file.filename}")

    temp_path = None

    try:
        # Guardar archivo
        with tempfile.NamedTemporaryFile(delete=False, suffix=".dxf") as tmp:
            content = await file.read()
            logger.info(f"✅ Read {len(content)} bytes")

            if len(content) == 0:
                raise HTTPException(400, "El archivo está vacío")

            tmp.write(content)
            temp_path = tmp.name

        # Detectar formato
        file_info = detect_file_format(temp_path)
        logger.info(f"📊 File info: {file_info}")

        # Si es DWG, rechazar con instrucciones
        if file_info["is_dwg"] and not file_info["is_dxf"]:
            logger.warning("❌ DWG file detected, conversion required")
            return JSONResponse(
                status_code=400,
                content={
                    "error": "Archivo DWG no soportado",
                    "message": "Este servicio solo acepta archivos DXF",
                    "detected_format": "DWG",
                    "detected_version": file_info["version"],
                    "how_to_convert": {
                        "option_1": {
                            "name": "AutoCAD/BricsCAD",
                            "steps": [
                                "1. Abre el archivo DWG",
                                "2. File → Save As",
                                "3. Elige formato: DXF",
                                "4. Tipo: ASCII (no Binary)",
                                "5. Versión: AutoCAD 2013 o superior",
                            ],
                        },
                        "option_2": {
                            "name": "LibreCAD (gratis)",
                            "url": "https://librecad.org/",
                            "steps": [
                                "1. Descarga LibreCAD (gratis)",
                                "2. File → Open → selecciona tu DWG",
                                "3. File → Save As → formato DXF",
                            ],
                        },
                        "option_3": {
                            "name": "Convertidor online",
                            "url": "https://www.zamzar.com/convert/dwg-to-dxf/",
                            "note": "Sube tu DWG y descarga el DXF",
                        },
                    },
                },
            )

        # Intentar leer el DXF
        try:
            logger.info("📖 Reading DXF file...")
            doc = ezdxf.readfile(temp_path)
            logger.info("✅ DXF loaded successfully")
        except DXFStructureError as e:
            logger.error(f"❌ DXF structure error: {e}")
            raise HTTPException(
                400,
                detail={
                    "error": "Archivo DXF corrupto o inválido",
                    "message": str(e),
                    "suggestion": "Intenta guardar el archivo nuevamente desde AutoCAD",
                },
            )
        except Exception as e:
            logger.error(f"❌ Error reading file: {e}")
            raise HTTPException(
                400,
                detail={
                    "error": "No se pudo leer el archivo",
                    "message": str(e),
                    "suggestion": "Asegúrate de que sea un archivo DXF válido (ASCII, no Binary)",
                },
            )

        # Extraer entidades
        msp = doc.modelspace()
        results = []
        entity_stats = {}

        for entity in msp:
            kind = entity.dxftype()
            layer = entity.dxf.layer

            # Estadísticas
            entity_stats[kind] = entity_stats.get(kind, 0) + 1

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
                        "area": round(3.14159 * entity.dxf.radius**2, 4),
                    }
                elif kind == "ARC":
                    entity_data = {
                        "center": list(entity.dxf.center),
                        "radius": round(entity.dxf.radius, 4),
                        "start_angle": round(entity.dxf.start_angle, 2),
                        "end_angle": round(entity.dxf.end_angle, 2),
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
                    entity_data = {
                        "points": points,
                        "closed": entity.closed,
                        "point_count": len(points),
                    }
                elif kind == "POLYLINE":
                    points = [list(v.dxf.location) for v in entity.vertices]
                    entity_data = {
                        "points": points,
                        "closed": entity.is_closed,
                        "point_count": len(points),
                    }
                elif kind == "SPLINE":
                    # Splines son curvas complejas
                    entity_data = {
                        "degree": entity.dxf.degree,
                        "control_point_count": len(entity.control_points),
                    }
                else:
                    # Otras entidades: solo metadata
                    entity_data = {"type": kind}

                results.append({"kind": kind, "layer": layer, "data": entity_data})

            except Exception as e:
                logger.warning(f"⚠️  Error processing {kind} entity: {e}")
                continue

        logger.info(f"✅ Extracted {len(results)} entities")
        logger.info(f"📊 Entity stats: {entity_stats}")

        return {
            "success": True,
            "file_name": file.filename,
            "file_format": "DXF",
            "file_size_bytes": file_info["file_size"],
            "total_entities": len(results),
            "entity_statistics": entity_stats,
            "elements": results,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}", exc_info=True)
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
