import unicodedata


def norm(text: str | None) -> str:
    """Normalize text for accent- and case-insensitive comparison.

    Order matters: dotted/dotless I must be mapped before lowercasing.
    """
    if text is None:
        return ""
    t = text.replace("İ", "i").replace("I", "ı").lower().replace("ı", "i")
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return "".join(c for c in t if c.isalnum())
