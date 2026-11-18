"""Fail-closed selection of explicitly frozen source versions."""


def matches_version_pins(source_name, version, pins):
    if not pins:
        return True
    # Import lazily: rag's public module imports the retriever on startup.
    from app.services.rag.citation_trust import base_source_title, normalize_version

    import re
    def title_key(value):
        return base_source_title(re.sub(r"\.(?:pdf|docx?|xlsx?|txt|md)$", "", str(value or ""), flags=re.I))
    title = title_key(source_name)
    actual = normalize_version(version)
    if not title or actual is None:
        return False
    matches = [normalize_version(value) for key, value in pins.items()
               if title_key(key) == title]
    return bool(matches) and all(value is not None and value == actual for value in matches)
