# visual_loader.py
import json
from pathlib import Path

def load_visual_schema(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    with p.open('r', encoding='utf-8') as f:
        return json.load(f)

def load_and_harmonize(annotation_path: str, canonical_schema: str):
    from .schemas.schema_harmonizer import SchemaHarmonizer
    h = SchemaHarmonizer(canonical_schema)
    return h.validate_and_harmonize(annotation_path)
