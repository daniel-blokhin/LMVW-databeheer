"""Prompt for required secrets without echo or shell history, then run the live CLI."""
from __future__ import annotations

import argparse
import getpass
import os
import warnings
from pathlib import Path

from lmvw_pipeline.cli import main
from lmvw_pipeline.config import load_config


def launch() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    config = load_config(args.config)
    if config.mode != "live":
        parser.error("This helper accepts only an explicitly live configuration")
    settings = config.values["sources"]
    required = []
    if settings.get("dso"):
        required.append("DSO_API_KEY_" + settings["dso_environment"])
    if settings.get("rp"):
        required.append("RUIMTELIJKE_PLANNEN_API_KEY")
    temporary = []
    try:
        for name in required:
            if not os.environ.get(name) and not os.environ.get(name + "_FILE"):
                with warnings.catch_warnings():
                    # Refuse environments that would fall back to echoing a credential.
                    warnings.simplefilter("error", getpass.GetPassWarning)
                    value = getpass.getpass(name + " (hidden input): ")
                os.environ[name] = value
                temporary.append(name)
        command = ["run", "--config", str(args.config)]
        if args.output_dir:
            command += ["--output-dir", str(args.output_dir)]
        return main(command)
    finally:
        for name in temporary:
            os.environ.pop(name, None)
        # Python does not guarantee zeroisation of immutable strings in process memory.


if __name__ == "__main__":
    raise SystemExit(launch())
