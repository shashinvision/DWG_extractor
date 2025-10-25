from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import ezdxf
import tempfile
import os
import subprocess
import logging
from typing import Optional
import shutil

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="DWG Extractor", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def detect_dwg_version(file_path: str) -> dict:
    """Detecta la versión del archivo DWG/DXF"""
    with open(file_path, "rb") as f:
        header = f.read(100)

    try:
        text_header = header[:50].decode("ascii")
        is_text = True
        file_type = "DXF"
    except:
        is_text = False
        file_type = "DWG"

    dwg_version = "Unknown"
    if header.startswith(b"AC"):
        version_code = header[0:6].decode("ascii", errors="ignore")
        dwg_versions = {
            "AC1032": "AutoCAD 2018-2021",
            "AC1027": "AutoCAD 2013-2017",
            "AC1024": "AutoCAD 2010-2012",
            "AC1021": "AutoCAD 2007-2009",
            "AC1018": "AutoCAD 2004-2006",
        }
        dwg_version = dwg_versions.get(version_code, version_code)

    return {
        "file_type": file_type,
        "is_text": is_text,
        "dwg_version": dwg_version,
        "file_size": os.path.getsize(file_path),
    }


def convert_dwg_to_dxf(dwg_path: str) -> str:
    """Convierte DWG a DXF usando ODA File Converter"""
    logger.info(f"🔄 Converting DWG to DXF: {dwg_path}")

    # Crear directorios temporales
    input_dir = tempfile.mkdtemp(prefix="dwg_in_")
    output_dir = tempfile.mkdtemp(prefix="dwg_out_")

    try:
        # Copiar archivo al directorio de entrada
        input_file = os.path.join(input_dir, "input.dwg")
        shutil.copy(dwg_path, input_file)

        # Ejecutar ODA File Converter
        # Sintaxis: ODAFileConverter input_folder output_folder output_version file_type recurse audit
        cmd = [
            "/usr/bin/ODAFileConverter",
            input_dir,
            output_dir,
            "ACAD2018",  # Versión de salida
            "DXF",  # Formato de salida
            "0",  # No recursivo
            "1",  # Audit
        ]

        logger.info(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            logger.error(f"ODA Converter error: {result.stderr}")
            raise Exception(f"Conversion failed: {result.stderr}")

        # Buscar el archivo DXF generado
        dxf_files = [f for f in os.listdir(output_dir) if f.endswith(".dxf")]

        if not dxf_files:
            raise Exception("No DXF file generated")

        dxf_path = os.path.join(output_dir, dxf_files[0])
        logger.info(f"✅ DXF created: {dxf_path}")

        return dxf_path

    except subprocess.TimeoutExpired:
        raise Exception("Conversion timeout (30s)")
    except Exception as e:
        raise Exception(f"Conversion error: {str(e)}")
    finally:
        # Limpiar directorio de entrada
        try:
            shutil.rmtree(input_dir)
        except:
            pass


@app.get("/health")
async def health_check():
    # Verificar que ODA Converter esté instalado
    oda_installed = os.path.exists("/usr/bin/ODAFileConverter")
    return {
        "status": "ok",
        "service": "dwg-extractor",
        "oda_converter": "installed" if oda_installed else "missing",
    }


@app.post("/extract")
async def extract_dwg(file: Optional[UploadFile] = File(None)):
    logger.info(f"=== New Request ===")

    if not file:
        raise HTTPException(400, "No se recibió ningún archivo")

    logger.info(f"📄 File: {file.filename}")

    temp_dwg_path = None
    temp_dxf_path = None
    output_dir = None

    try:
        # Guardar archivo subido
        with tempfile.NamedTemporaryFile(delete=False, suffix=".dwg") as tmp:
            content = await file.read()
            logger.info(f"✅ Read {len(content)} bytes")

            if len(content) == 0:
                raise HTTPException(400, "El archivo está vacío")

            tmp.write(content)
            temp_dwg_path = tmp.name

        # Detectar tipo
        file_info = detect_dwg_version(temp_dwg_path)
        logger.info(f"📊 File info: {file_info}")

        # Intentar leer directamente (si es DXF)
        doc = None
        if file_info["is_text"]:
            logger.info("📖 File is DXF, reading directly...")
            try:
                doc = ezdxf.readfile(temp_dwg_path)
                logger.info("✅ DXF read successful")
            except Exception as e:
                logger.warning(f"Failed to read DXF: {e}")

        # Si es DWG o falló la lectura DXF, convertir
        if doc is None:
            logger.info("🔄 Converting DWG to DXF...")
            try:
                temp_dxf_path = convert_dwg_to_dxf(temp_dwg_path)
                # Guardar referencia al output_dir para limpiarlo después
                output_dir = os.path.dirname(temp_dxf_path)

                doc = ezdxf.readfile(temp_dxf_path)
                logger.info("✅ Converted DXF read successful")
            except Exception as e:
                logger.error(f"❌ Conversion failed: {e}")
                raise HTTPException(
                    422,
                    detail={
                        "error": "No se pudo convertir el archivo",
                        "file_info": file_info,
                        "message": str(e),
                        "suggestion": "Convierte manualmente a DXF ASCII usando AutoCAD",
                    },
                )

        # Extraer entidades
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
                    continue

                results.append({"kind": kind, "layer": layer, "data": entity_data})
            except Exception as e:
                logger.warning(f"Error processing {kind}: {e}")
                continue

        logger.info(f"✅ Extracted {len(results)} entities")

        return {
            "file_name": file.filename,
            "file_type": file_info["file_type"],
            "dwg_version": file_info["dwg_version"],
            "count": len(results),
            "elements": results,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}", exc_info=True)
        raise HTTPException(500, f"Error interno: {str(e)}")
    finally:
        # Limpieza
        if temp_dwg_path and os.path.exists(temp_dwg_path):
            try:
                os.unlink(temp_dwg_path)
            except:
                pass
        if output_dir and os.path.exists(output_dir):
            try:
                shutil.rmtree(output_dir)
            except:
                pass


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8083, log_level="info")
