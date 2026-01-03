"""
schema_harmonizer.py
Normalizes any annotation JSON to match the visual_canonical_schema.json rules.
"""

import json
from pathlib import Path

class SchemaHarmonizer:

    def __init__(self, canonical_schema_path: str):
        self.canonical = self._load(canonical_schema_path)

    def _load(self, p: str):
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)

    def validate_and_harmonize(self, annotation_json_path: str) -> dict:
        """
        Loads an annotation JSON (user-annotated), validates classes + fields,
        normalizes bbox structures, removes invalid entries, and ensures
        all class definitions match the canonical schema.
        """
        with open(annotation_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if "pages" not in data:
            raise ValueError("Annotation missing required section: pages[]")

        classes = self.canonical["classes"]

        for page in data["pages"]:
            if "regions" not in page:
                continue

            for class_name, items in page["regions"].items():

                if class_name not in classes:
                    print(f"[WARN] Unknown class '{class_name}', keeping but marking as 'unknown_class'")
                    page["regions"][class_name] = self._tag_unknown(items)
                    continue

                page["regions"][class_name] = self._clean_items(
                    class_name, items, classes[class_name]
                )

        return data

    def _clean_items(self, class_name: str, items: list, class_rules: dict):
        """
        Applies field validation + color correction + bbox sanity rules.
        """
        required = set(class_rules["required_fields"])
        allowed = set(class_rules.get("allowed_fields", []))
        color_target = class_rules["color_hex"]

        cleaned = []

        for item in items:
            # Validate required fields
            if not required.issubset(item.keys()):
                print(f"[DROP] {class_name} missing required fields → {item}")
                continue

            # Force canonical color
            item["color_hex"] = color_target

            # Remove fields not allowed
            item = {k: v for k, v in item.items() if k in required or k in allowed}

            # Validate bbox
            if not self._valid_bbox(item["bbox"]):
                print(f"[DROP] Invalid bbox for {class_name}: {item['bbox']}")
                continue

            cleaned.append(item)

        return cleaned

    def _valid_bbox(self, bbox):
        if len(bbox) != 4:
            return False
        x0, y0, x1, y1 = bbox
        if x1 <= x0 or y1 <= y0:
            return False
        return True

    def _tag_unknown(self, items):
        for i in items:
            i["unknown_class"] = True
        return items

