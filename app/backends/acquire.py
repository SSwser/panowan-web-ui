import subprocess
import tempfile
from pathlib import Path

from .spec import BackendSpec


def acquire_backend_source(spec: BackendSpec) -> tempfile.TemporaryDirectory[str]:
    temp_dir = tempfile.TemporaryDirectory()
    root = Path(temp_dir.name)

    subprocess.run(
        [
            "git",
            "clone",
            "--no-checkout",
            "--depth",
            "1",
            "--branch",
            spec.source.revision,
            spec.source.url,
            str(root),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "sparse-checkout", "init", "--cone"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )

    top_level = sorted(
        {
            pattern.split("/", 1)[0]
            for pattern in spec.filter.include
            if pattern and pattern.split("/", 1)[0] not in {"**", "*"}
        }
    )
    if top_level:
        subprocess.run(
            ["git", "sparse-checkout", "set", *top_level],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

    subprocess.run(
        ["git", "checkout", spec.source.revision],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    # The acquired source tree is temporary input only; deleting its .git dir is
    # unnecessary because materialization copies only filtered files into vendor/.
    # Keeping the checkout intact avoids Windows file-handle races on packed refs.
    return temp_dir
