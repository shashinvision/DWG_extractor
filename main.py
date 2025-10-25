from fastapi import FastAPI, File, UploadFile
from pydantic import BaseModel
import ezdxf
import tempfile
import uuid
import json

app = FastAPI(title="DWG Extractor")


class ExtractedElement(BaseModel):
    kind: str
    layer: str
    data: dict


@app.post("/extract")
async def extract_dwg(file: UploadFile = File(...)):
    # Save temp file
    temp_path = f"/tmp/{uuid.uuid4()}.dwg"
    with open(temp_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # Load with ezdxf
    doc = ezdxf.readfile(temp_path)
    msp = doc.modelspace()

    results = []
    for entity in msp:
        kind = entity.dxftype()
        layer = entity.dxf.layer

        # Extraer datos según tipo de entidad
        data = {}
        if kind == "LINE":
            data = {
                "start": list(entity.dxf.start),
                "end": list(entity.dxf.end),
                "length": entity.dxf.start.distance(entity.dxf.end),
            }
        elif kind == "CIRCLE":
            data = {"center": list(entity.dxf.center), "radius": entity.dxf.radius}
        elif kind == "TEXT":
            data = {
                "text": entity.dxf.text,
                "insert": list(entity.dxf.insert),
                "height": entity.dxf.height,
            }
        else:
            continue  # Solo tomamos entidades útiles para RAG

        results.append(ExtractedElement(kind=kind, layer=layer, data=data))

    return {
        "file_name": file.filename,
        "count": len(results),
        "elements": [e.dict() for e in results],
    }
