from backbone.visual.visual_pipeline_integrator import VisualPipelineIntegrator
from backbone.visual.visual_chunker_bridge import VisualChunkerBridge
from backbone.chunking.chunker import Chunker

print("\n>>> STEP 1: Running visual pipeline...")
v = VisualPipelineIntegrator()
vres = v.run(
    pdf_path="test.pdf",
    annotation_path="backbone/visual/schemas/page3_annotation.json",
    schema_path="backbone/visual/schemas/visual_note_schema.json",
    score_notes=True,
    make_debug_overlays=True,
    debug_output_dir="visual_debug"
)

print(" - Visual pages loaded:", list(vres["pages"].keys()))
print(" - Total visual notes:", len(vres["fused_notes"]))

print("\n>>> STEP 2: Running text chunker...")
c = Chunker()
text_chunks = c.process("test.pdf")
print(" - Total text chunks:", len(text_chunks))

print("\n>>> STEP 3: Attaching visual metadata...")
bridge = VisualChunkerBridge()

page1_visual = vres["pages"].get(1)
page1_chunks = [ch for ch in text_chunks if ch.page == 1]

bridge.attach_visual_metadata(page1_chunks, page1_visual)

print("\n>>> SAMPLE CHUNK METADATA (first 5):")
for ch in page1_chunks[:5]:
    print({
        "text": ch.content[:50],
        "visual_region_class": ch.metadata.get("visual_region_class"),
        "visual_note_id": ch.metadata.get("visual_note_id"),
        "visual_column_id": ch.metadata.get("visual_column_id"),
        "visual_confidence": ch.metadata.get("visual_confidence"),
    })
