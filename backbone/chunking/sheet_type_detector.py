def detect_sheet_type(page_number, chunks):
    """
    Determine sheet type. Signature must match chunker.py caller.

    page_number: int
    chunks: list of Chunk objects for the page
    """

    # --- Minimal placeholder logic (works fine until you customize) ---
    text_joined = " ".join((c.content or "").lower() for c in chunks)

    if "note" in text_joined or "general notes" in text_joined:
        return "notes_sheet"

    return "general"
