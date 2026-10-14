"""Receipt verifies both transport digest and post-decompression content."""
from pathlib import Path
import gzip
import hashlib
import sys
import tempfile

from crosscheck import scenario

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from prepare_session import prepare


def main():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        raw, _ = scenario(47)
        archive = d / "sample.NASDAQ_ITCH50.gz"
        with gzip.open(archive, "wb") as gz:
            gz.write(raw)
        digest = hashlib.md5(archive.read_bytes(), usedforsecurity=False).hexdigest()
        sidecar = d / "download.md5sum"
        sidecar.write_text(f"{digest}  {archive.name}\n")
        expanded = d / "sample.NASDAQ_ITCH50"
        receipt = prepare(archive, expanded, sidecar)
        assert expanded.read_bytes() == raw
        assert receipt["published_md5_verified"]
        assert receipt["uncompressed_sha256"] == hashlib.sha256(raw).hexdigest()
        try:
            prepare(archive, expanded, sidecar)
        except ValueError:
            pass
        else:
            raise AssertionError("must not overwrite existing output")
        sidecar.write_text("0" * 32 + "  " + archive.name + "\n")
        try:
            prepare(archive, d / "other", sidecar)
        except ValueError:
            pass
        else:
            raise AssertionError("must reject bad published checksum")
        print("compressed archive integrity checks passed")


if __name__ == "__main__":
    main()
