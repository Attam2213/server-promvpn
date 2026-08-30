import json
import os
from fastapi import APIRouter, HTTPException, Body
from ..services.config_generator import ConfigGenerator

router = APIRouter(prefix="/api/configs", tags=["configs"])

_config_generator = ConfigGenerator()


def _get_schema_path() -> str:
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "editable-fields.json",
    )


@router.get("/schema")
async def get_schema():
    schema_path = _get_schema_path()
    if not os.path.exists(schema_path):
        raise HTTPException(status_code=404, detail="Schema file not found")
    try:
        with open(schema_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Invalid JSON: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/validate")
async def validate_config(values: dict = Body(...)):
    try:
        result = _config_generator.validate(values)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/build")
async def build_config(values: dict = Body(...)):
    try:
        validation = _config_generator.validate(values)
        if not validation["valid"]:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Validation failed",
                    "errors": validation["errors"],
                },
            )

        template_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "templates",
        )
        config_text = _config_generator.build_config(values, template_dir)
        file_name = _config_generator.build_file_name(values)

        return {
            "config_text": config_text,
            "file_name": file_name,
            "valid": True,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
