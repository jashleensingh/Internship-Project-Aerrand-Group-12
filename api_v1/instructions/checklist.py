"""POST /v1/checklists/generate. In Aerrand this calls the item-checklist model. This stand-in uses simple keyword
rules so the endpoint, its shape and its 'never fails the booking' contract can be built and tested now.

Contract: always 200. If anything goes wrong, return empty lists (treat as 'no suggestion')."""
TAGS = ["Marketplace", "Food", "Electronics", "Documents", "Clothing",
        "Groceries", "Furniture", "Gifts", "Medical", "Fragile"]
SIZES = ("small", "medium", "large", "xlarge")

RULES = [  # (keywords, tags, size, checks)
    (("tv", "television", "monitor", "laptop", "phone", "console", "qled"), ["Electronics", "Fragile"], "xlarge",
     ["Check the screen for cracks, scratches or dead pixels", "Check the bezel and corners for impact damage",
      "Check the rear panel for missing mount screws", "Check the ports and cable inputs for bent pins"]),
    (("sofa", "couch", "table", "desk", "chair", "dresser", "bed"), ["Furniture"], "xlarge",
     ["Check the frame and legs for cracks or wobble", "Check the surface for deep scratches or stains",
      "Check that screws and fittings are included"]),
    (("pizza", "food", "cake", "meal"), ["Food"], "medium",
     ["Check the packaging is sealed and upright", "Check the item is still at the right temperature"]),
    (("document", "contract", "passport", "paper"), ["Documents"], "small",
     ["Check the envelope is sealed", "Check the name on the package matches the order"]),
]


def generate(description, quantity=None, size=None, price=None):
    try:
        text = (description or "").lower()
        checks, tags, suggested = [], [], None
        for words, rtags, rsize, rchecks in RULES:
            if any(w in text.split() or w in text for w in words):
                checks += rchecks
                tags += rtags
                suggested = suggested or rsize
        if price and "Marketplace" not in tags:
            tags.append("Marketplace")
        checks = [c[:80] for c in dict.fromkeys(checks)][:5]
        tags = [t for t in dict.fromkeys(tags) if t in TAGS][:3]
        return {"checklist": checks, "suggested_size": suggested if suggested in SIZES else None,
                "suggested_tags": tags}
    except Exception:
        return {"checklist": [], "suggested_size": None, "suggested_tags": []}
