# visual_note_parser.py
from typing import Dict, List

def parse_visual_structure(schema: Dict) -> Dict:
    # Returns structured columns/headers/notes from schema
    ps = schema.get("page_structure", {})
    return {
        "columns": ps.get("columns", []),
        "headers": ps.get("column_headers", []),
        "notes": ps.get("notes", []),
        "legend": ps.get("legend_boxes", []),
        "xenoglyphs": ps.get("xenoglyph_boxes", []),
    }
