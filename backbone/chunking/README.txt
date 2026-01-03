1. Files included in the ZIP

All paths are inside the ZIP root:

backbone/visual/visual_pipeline_integrator.py
backbone/visual/visual_debug.py
backbone/visual/visual_confidence.py
backbone/visual/visual_chunker_bridge.py
backbone/visual/auto_box_detector.py


No placeholders. All modules are fully implemented.

These are additions only. They do not overwrite any of your existing files.

2. Where to put them in your project

Extract the ZIP into your project root so the structure becomes:

C:\Projects\backbone_skeleton\
    backbone\
        chunking\
            chunk.py
            chunker.py
            structural_extractor.py
            sheet_type_detector.py
            column_detector.py
            semantic_grouper.py
            ...
        visual\
            visual_pipeline_integrator.py
            visual_debug.py
            visual_confidence.py
            visual_chunker_bridge.py
            auto_box_detector.py
            (plus the files you already added earlier)
            visual_loader.py
            visual_note_parser.py
            visual_to_text_fusion.py
            schemas\
                visual_note_schema.json  (your JSON schema, if present)


If backbone/visual or backbone/visual/schemas don’t exist, create them, then place these files accordingly.

3. What each new module does
visual_pipeline_integrator.py

Class: VisualPipelineIntegrator

Orchestrates the full visual pipeline:

Loads schema via your existing visual_loader.load_visual_schema

Parses structure via your visual_note_parser.parse_visual_structure

Fuses boxes → text via your visual_to_text_fusion.fuse_visual_and_text

Scores notes via VisualNoteScorer (from visual_confidence.py)

Optionally generates visual debug PNGs via draw_visual_debug_images

Primary API:

from backbone.visual.visual_pipeline_integrator import VisualPipelineIntegrator

vpi = VisualPipelineIntegrator()
result = vpi.run(
    pdf_path="test.pdf",
    schema_path="backbone/visual/schemas/visual_note_schema.json",
    score_notes=True,
    make_debug_overlays=True,
    debug_output_dir="visual_debug",
)

fused_notes = result["fused_notes"]

visual_debug.py

Function: draw_visual_debug_images(pdf_path, schema, output_dir, dpi=150)

Uses PyMuPDF + Pillow to:

Render each page of the PDF

Draw colored rectangles for:

columns

column headers

notes

legend boxes

sheet_info

xenoglyphs

whole_sheet (if present)

Save images like:

visual_debug/visual_page_1.png

visual_debug/visual_page_2.png

etc.

Reads color definitions from schema["color_classes"].

visual_confidence.py

Class: VisualNoteScorer

Adds confidence scoring to fused notes.

Uses heuristic features (as specified in your JSON rules):

color_match vs color_classes["note"]["hex"]

text_presence (any text?)

bullet_pattern (does text look like "1.", "(2)", "A.", "(A)" etc.)

left_indent_alignment (bbox not at extreme left)

bounding_box_ratio (height/width within a reasonable range)

Main APIs:

from backbone.visual.visual_confidence import VisualNoteScorer

scorer = VisualNoteScorer()
scored = scorer.score_fused_notes(
    schema=schema,
    original_notes=schema["page_structure"]["notes"],
    fused_notes=fused_notes
)


VisualPipelineIntegrator.run() already calls this for you and returns fused_notes with:

{
    "bbox": [...],
    "page_number": ...,
    "class": "note",
    "color_hex": "...",
    "text": "...",
    "confidence_score": float,
    "confidence_features": {...}
}

visual_chunker_bridge.py

Class: VisualAwareChunker

Bridges the visual pipeline into your Chunk world without modifying chunker.py.

Internally uses:

backbone.chunking.chunker.Chunker

backbone.chunking.chunk.Chunk

VisualPipelineIntegrator

Main API:

from backbone.visual.visual_chunker_bridge import VisualAwareChunker

vac = VisualAwareChunker()
visual_chunks = vac.process_visual_notes_sheet(
    pdf_path="test.pdf",
    schema_path="backbone/visual/schemas/visual_note_schema.json"
)


Returns a list of Chunk objects with:

type="visual_note"

content=text_from_pdf

bbox=note_bbox

page_number=note_page

metadata["source"] = "visual_pipeline"

metadata["confidence_score"] populated

This is your integration point for eventually wiring visual notes into your main notes-sheet processing.

auto_box_detector.py

Function: detect_boxes_from_pdf(pdf_path, page_number=1, dpi=150, color_classes=None, color_tolerance=10) -> dict

Pipeline:

Rasterizes a PDF page at a given DPI using PyMuPDF

Uses Pillow to detect connected regions of each configured color

Converts pixel boxes back into PDF coordinate system

Returns a schema-like dict:

{
  "metadata": {...},
  "color_classes": {...},
  "page_structure": {
      "whole_sheet_bbox": {...} or None,
      "sheet_info_bbox": {...} or None,
      "columns": [...],
      "column_headers": [...],
      "notes": [...],
      "legend_boxes": [...],
      "xenoglyph_boxes": [...],
  }
}


Each detected box has:

{
    "id": "note_1",
    "bbox": [x0, y0, x1, y1],
    "page_number": page,
    "class": "note",
    "color_hex": "#00F900"
}


You can then save this dict to JSON and use it as the schema:

import json
from backbone.visual.auto_box_detector import detect_boxes_from_pdf

schema_like = detect_boxes_from_pdf("test.pdf", page_number=3)
with open("backbone/visual/schemas/auto_page3.json", "w", encoding="utf-8") as f:
    json.dump(schema_like, f, indent=2)

4. How to run the whole visual pipeline (standalone)

Example end-to-end:

from backbone.visual.auto_box_detector import detect_boxes_from_pdf
from backbone.visual.visual_pipeline_integrator import VisualPipelineIntegrator
import json

pdf_path = "test.pdf"
page_num = 3
schema_path = "backbone/visual/schemas/page3_auto.json"

# 1) Auto-detect boxes and save schema
schema_like = detect_boxes_from_pdf(pdf_path, page_number=page_num)
with open(schema_path, "w", encoding="utf-8") as f:
    json.dump(schema_like, f, indent=2)

# 2) Run visual pipeline
vpi = VisualPipelineIntegrator()
result = vpi.run(
    pdf_path=pdf_path,
    schema_path=schema_path,
    score_notes=True,
    make_debug_overlays=True,
    debug_output_dir="visual_debug"
)

fused_notes = result["fused_notes"]
print(f"Got {len(fused_notes)} visual notes with scores.")

5. Log of variables / TODOs for after integration

These are the knobs and integration points you’ll likely want to adjust once the files are in place:

Color definitions

auto_box_detector.detect_boxes_from_pdf uses hardcoded hex values:

column: #00FDFF

column_header: #FF2600

note: #00F900

legend: #AA7942

sheet_info: #0433FF

whole_sheet: #FF9300

xenoglyph: #FF40FF

TODO: centralize in a config so annotations and detector share one source of truth.

Color tolerance

color_tolerance default is 10.

TODO: tune based on your export pipeline (anti-aliasing can smear colors).

DPI for rasterization

detect_boxes_from_pdf uses dpi=150.

Must align with how you drew boxes originally.

TODO: confirm DPI used when you annotated the sheets.

Note alignment: original_notes vs fused_notes

VisualNoteScorer.score_fused_notes assumes:

schema["page_structure"]["notes"]  ↔  fused_notes (same order)


TODO: if your schema ever reorders notes, we will need an explicit ID-based match instead of index-based.

Chunker integration

VisualAwareChunker.process_visual_notes_sheet() currently:

does NOT insert visual notes into Chunker.process();

it returns an independent list of Chunk objects with type="visual_note".

TODO: once you’re happy with visual performance, we can:

merge these into the main pipeline for notes sheets

or replace text-based grouping with visual notes for specific sheet types.

Confidence weight tuning

VisualNoteScorer.weights:

{
  "color_match": 0.25,
  "text_presence": 0.25,
  "bullet_pattern": 0.20,
  "left_indent_alignment": 0.15,
  "bounding_box_ratio": 0.15,
}


TODO: adjust weights once you see real scores on multiple projects.

Bullet pattern

BULLET_RE currently catches:

1., (2), A., (A) at start of note.

TODO: extend pattern for your full note style set if needed.

Bounding box heuristics

Height/width ratio heuristic is very general:

Accepts 0.3 <= h/w <= 3.0

TODO: tighten or loosen based on typical note block geometry.

Legend and sheet_info behavior

Detector only picks:

first whole_sheet bbox → page_structure["whole_sheet_bbox"]

first sheet_info bbox → page_structure["sheet_info_bbox"]

TODO: if you draw multiple separate sheet-info boxes, schema model may need extending.

If you want the next step to be:

Wiring visual notes directly into chunker.process(), or

Building a side-by-side evaluator (visual vs text grouping),

say what you want next and we’ll move that piece forward.