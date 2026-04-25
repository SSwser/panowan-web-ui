import hashlib
import os
import ssl
import urllib.request
from typing import Protocol

from .model_spec import ModelSpec

try:
    from huggingface_hub import snapshot_download
except ImportError:  # pragma: no cover
    snapshot_download = None  # type: ignore[assignment]


def _make_ssl_context() -> ssl.SSLContext:
    """Return an SSL context that verifies certificates.

    Prefers *certifi*'s CA bundle (available whenever huggingface_hub is
    installed) so that uv-managed Python builds — which do not link against
    the host OS CA store — can still verify HTTPS connections.
    """
    ctx = ssl.create_default_context()
    try:
        import certifi  # type: ignore[import-untyped]

        ctx.load_verify_locations(cafile=certifi.where())
    except ImportError:
        pass  # fall back to default CA search (works on most system Pythons)
    return ctx


class ModelProvider(Protocol):
    def ensure(self, spec: ModelSpec) -> None: ...
    def verify(self, spec: ModelSpec) -> None: ...


def _check_sha256(path: str, expected: str) -> bool:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest() == expected


class HuggingFaceProvider:
    """Downloads model assets from Hugging Face Hub."""

    def _all_files_present(self, spec: ModelSpec) -> bool:
        for f in spec.files:
            full_path = os.path.join(spec.target_dir, f.path)
            if not os.path.isfile(full_path):
                return False
            if f.sha256 and not _check_sha256(full_path, f.sha256):
                return False
        return True

    def verify(self, spec: ModelSpec) -> None:
        for f in spec.files:
            full_path = os.path.join(spec.target_dir, f.path)
            if not os.path.isfile(full_path):
                raise FileNotFoundError(
                    f"Missing model file: {full_path} (spec: {spec.name})"
                )
            if f.sha256 and not _check_sha256(full_path, f.sha256):
                raise RuntimeError(f"Hash mismatch for {full_path} (spec: {spec.name})")

    def ensure(self, spec: ModelSpec) -> None:
        if self._all_files_present(spec):
            return
        if snapshot_download is None:
            raise RuntimeError(
                f"huggingface_hub is not installed; install it with `pip install huggingface_hub` "
                f"to enable downloading {spec.name} from {spec.source_ref}"
            )
        # Note: revision is not pinned; integrity is enforced via FileCheck.sha256 when set.
        # huggingface_hub uses background threads for downloads; KeyboardInterrupt
        # only interrupts the main thread. Register a signal handler so Ctrl+C
        # during make init actually terminates the process instead of hanging.
        import signal

        prev_handler = signal.getsignal(signal.SIGINT)

        def _interrupt_on_sigint(signum: int, frame: object) -> None:
            raise KeyboardInterrupt

        signal.signal(signal.SIGINT, _interrupt_on_sigint)
        try:
            snapshot_download(
                repo_id=spec.source_ref,
                local_dir=spec.target_dir,
            )
        finally:
            signal.signal(signal.SIGINT, prev_handler)
        if not self._all_files_present(spec):
            raise RuntimeError(
                f"Download completed but files still missing for {spec.name}"
            )


class SubmoduleProvider:
    """Validates third_party-backed assets that are built into the image.

    Submodule artifacts are populated by `git submodule update --init` (run as
    part of `make init` / `make setup-submodules`) before this provider is
    invoked, so on the host they are guaranteed to already exist — no download
    is needed.  In the container they are bind-mounted from the host submodule
    checkout, so they are also guaranteed to exist.  This provider therefore
    validates only; it never downloads anything.
    """

    def _require_present(self, spec: ModelSpec) -> None:
        for file_check in spec.files:
            full_path = os.path.join(spec.target_dir, file_check.path)
            if not os.path.exists(full_path):
                raise FileNotFoundError(
                    f"Submodule artifact missing: {full_path}. "
                    f"This should be included in the Docker image via third_party/."
                )

    def ensure(self, spec: ModelSpec) -> None:
        # Submodules are populated by `make setup-submodules` before this runs;
        # nothing to download here — only validate that the files are present.
        self._require_present(spec)

    def verify(self, spec: ModelSpec) -> None:
        self._require_present(spec)


class HttpProvider:
    """Downloads single-file model artifacts from a direct HTTP(S) URL."""

    def _all_files_present(self, spec: ModelSpec) -> bool:
        for file_check in spec.files:
            full_path = os.path.join(spec.target_dir, file_check.path)
            if not os.path.isfile(full_path):
                return False
            if file_check.sha256 and not _check_sha256(full_path, file_check.sha256):
                return False
        return True

    def verify(self, spec: ModelSpec) -> None:
        for file_check in spec.files:
            full_path = os.path.join(spec.target_dir, file_check.path)
            if not os.path.isfile(full_path):
                raise FileNotFoundError(
                    f"Missing model file: {full_path} (spec: {spec.name})"
                )
            if file_check.sha256 and not _check_sha256(full_path, file_check.sha256):
                raise RuntimeError(f"Hash mismatch for {full_path} (spec: {spec.name})")

    def ensure(self, spec: ModelSpec) -> None:
        if self._all_files_present(spec):
            return
        if len(spec.files) != 1:
            raise RuntimeError(
                f"HTTP model spec must declare exactly one file: {spec.name}"
            )

        file_check = spec.files[0]
        os.makedirs(spec.target_dir, exist_ok=True)
        final_path = os.path.join(spec.target_dir, file_check.path)
        os.makedirs(os.path.dirname(final_path) or spec.target_dir, exist_ok=True)
        tmp_path = final_path + ".part"

        try:
            ssl_ctx = _make_ssl_context()
            with (
                urllib.request.urlopen(spec.source_ref, context=ssl_ctx) as response,
                open(tmp_path, "wb") as out,
            ):
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)

            if file_check.sha256 and not _check_sha256(tmp_path, file_check.sha256):
                raise RuntimeError(
                    f"Hash mismatch for downloaded {final_path} (spec: {spec.name})"
                )

            os.replace(tmp_path, final_path)
        except BaseException:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise

        if not self._all_files_present(spec):
            raise RuntimeError(
                f"Download completed but files still missing for {spec.name}"
            )
