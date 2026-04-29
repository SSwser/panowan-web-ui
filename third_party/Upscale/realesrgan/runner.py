from pathlib import Path
import runpy
import sys


def main() -> None:
    backend_root = Path(__file__).resolve().parent
    vendor_main = backend_root / "vendor" / "__main__.py"
    if not vendor_main.exists():
        raise FileNotFoundError(
            f"RealESRGAN runtime bundle is missing: {vendor_main}"
        )
    sys.argv[0] = str(vendor_main)
    runpy.run_path(str(vendor_main), run_name="__main__")


if __name__ == "__main__":
    main()
