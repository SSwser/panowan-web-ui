from pathlib import Path


def write_revision(vendor_dir: Path, revision: str) -> None:
    (vendor_dir / ".revision").write_text(f"{revision}\n", encoding="utf-8")
