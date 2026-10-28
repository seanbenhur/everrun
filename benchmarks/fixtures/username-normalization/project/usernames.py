def normalize_username(raw):
    if not raw:
        return None
    return raw.strip().lower()
