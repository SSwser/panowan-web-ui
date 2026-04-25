from pathlib import PurePosixPath


def _matches(path: str, pattern: str) -> bool:
    # PurePosixPath.full_match (Python 3.13+) treats `**` as a recursive glob
    # across path segments, which fnmatch does not. Required so patterns like
    # `realesrgan/**/test*` match both nested and top-level files.
    return PurePosixPath(path).full_match(pattern)


def filter_paths(paths: list[str], include: list[str], exclude: list[str]) -> list[str]:
    included = [
        p for p in paths if not include or any(_matches(p, pat) for pat in include)
    ]
    return [p for p in included if not any(_matches(p, pat) for pat in exclude)]
