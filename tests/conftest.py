# tests/conftest.py
import gzip, json, pathlib, pytest

SAMPLES = pathlib.Path(__file__).parent / "samples"

def load(folder: str, filename: str, binary: bool = False):
    """
    Read a fixture from tests/samples/, transparently handling .gz files.
    Set binary=True to return bytes, else str.
    """
    fp = SAMPLES / folder / filename
    if fp.suffix == ".gz":
        with gzip.open(fp, "rb") as f:
            data = f.read()
            return data if binary else data.decode("utf‑8")
    mode = "rb" if binary else "r"
    with open(fp, mode) as f:
        return f.read()
