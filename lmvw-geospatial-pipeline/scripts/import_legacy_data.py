"""Import only six private data files, never original code, credentials or API caches."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from lmvw_pipeline.common import PipelineError, file_sha256, write_json

NAMES = ("Planlijst demo beheer LMVW.xlsx", "LMVW demo plannen.gpkg", "bag_panden_db.csv",
         "bag_verblijfsobjecten_db.csv", "bag_verblijfsobject_pand_relatie_db.csv", "brk_percelen_db.csv")


def import_legacy(archive: Path, output: Path) -> dict:
    """Select latest-scope snapshots by an explicit path rule, not modification time."""
    if output.exists():
        raise PipelineError("Private target already exists; overwrite is disabled")
    selected = {}
    with zipfile.ZipFile(archive) as source:
        for name in NAMES:
            candidates = [i for i in source.infolist() if not i.is_dir() and PurePosixPath(i.filename).name == name
                          and ("/output_lmvw/" in "/" + i.filename if name.endswith("_db.csv") else i.filename.startswith("0. LMVW data/"))]
            if len(candidates) != 1:
                raise PipelineError("Missing or ambiguous legacy snapshot selection; inspect the migration guide")
            item = candidates[0]
            if ".." in PurePosixPath(item.filename).parts or item.file_size > 200_000_000:
                raise PipelineError("Unsafe archive member or size")
            selected[name] = item
        output.parent.mkdir(parents=True, exist_ok=True)
        temp = Path(tempfile.mkdtemp(prefix=".private-import-", dir=output.parent))
        try:
            imported = {}
            for name, item in selected.items():
                path = temp / name  # fixed allowlisted basename; never archive path extraction
                with source.open(item) as src, path.open("wb") as dst:
                    if os.name == "posix":
                        os.fchmod(dst.fileno(), 0o600)
                    written = 0
                    while chunk := src.read(1_048_576):
                        written += len(chunk)
                        if written > 200_000_000:
                            raise PipelineError("Archive member exceeded the import limit")
                        dst.write(chunk)
                imported[name] = {"bytes": written, "sha256": file_sha256(path)}
            report = {"classification": "PRIVATE_DO_NOT_COMMIT", "archive_sha256": file_sha256(archive), "files": imported}
            write_json(temp / "import_manifest.json", report)
            temp.rename(output)
        except BaseException:
            shutil.rmtree(temp, ignore_errors=True)
            raise
    return {"status": "IMPORTED_PRIVATE_DATA", "files": len(imported), "output": str(output)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("data/private"))
    args = parser.parse_args()
    try:
        print(json.dumps(import_legacy(args.archive, args.output)))
    except (PipelineError, OSError, zipfile.BadZipFile) as exc:
        raise SystemExit(f"Private import failed ({type(exc).__name__}); no code or cache was executed.") from None
