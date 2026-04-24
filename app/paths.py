import posixpath


def container_join(base: str, *parts: str) -> str:
    cleaned_parts = [part.strip("/") for part in parts if part]
    if not cleaned_parts:
        return base
    base_clean = base.rstrip("/") or "/"
    return posixpath.join(base_clean, *cleaned_parts)


def container_child(path: str, child: str) -> str:
    return container_join(path, child)
