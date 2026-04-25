import re
from pathlib import PurePosixPath


def _matches(path: str, pattern: str) -> bool:
    # PurePosixPath.full_match (Python 3.13+) treats `**` as a recursive glob
    # across path segments. Required so patterns like `realesrgan/**/test*`
    # match both nested and top-level files.
    p = PurePosixPath(path)
    if hasattr(p, "full_match"):
        return p.full_match(pattern)

    # Fallback for Python < 3.13: convert glob to regex.
    #
    # In Python 3.13+ full_match semantics, `**` matches zero or more
    # complete path segments. Surrounding slashes are consumed by `**`:
    #   realesrgan/**       → files under realesrgan/ at any depth
    #   **/*.md             → any .md file at any depth
    #   realesrgan/**/test* → test* under realesrgan/ at any depth
    #
    # Strategy: split on `/` to get path segments, then for each `**`
    # segment emit a regex that matches zero-or-more intermediate dirs.
    segs = pattern.split("/")
    regex_parts: list[str] = []
    i = 0
    while i < len(segs):
        seg = segs[i]
        if seg == "**":
            # ** matches zero or more complete path segments
            # (?:<segment>/)* — optionally match some segments with trailing /
            regex_parts.append("(?:[^/]+/)*")
        else:
            regex_parts.append(_glob_seg_to_regex(seg))
            # Add path separator unless this is the last segment
            if i < len(segs) - 1:
                regex_parts.append("/")
        i += 1
    # When pattern ends with **, also match the leaf filename
    if segs[-1] == "**":
        regex_parts.append("[^/]*")
    return bool(re.fullmatch("".join(regex_parts), path))


def _glob_seg_to_regex(seg: str) -> str:
    """Convert a single path-segment glob (no /) to a regex."""
    result = []
    for ch in seg:
        if ch == "*":
            result.append("[^/]*")
        elif ch == "?":
            result.append("[^/]")
        else:
            result.append(re.escape(ch))
    return "".join(result)


def filter_paths(paths: list[str], include: list[str], exclude: list[str]) -> list[str]:
    included = [
        p for p in paths if not include or any(_matches(p, pat) for pat in include)
    ]
    return [p for p in included if not any(_matches(p, pat) for pat in exclude)]
