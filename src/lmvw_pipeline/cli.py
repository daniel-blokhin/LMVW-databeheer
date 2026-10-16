"""Small command-line interface; expected failures never print secrets or tracebacks."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .common import PipelineError
from .contracts import sql_ddl
from .exporting import verify_bundle
from .pipeline import run_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lmvw", description="Housing data ingestion, quality control and spatial integration")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("run", "Run all stages through a database-ready export"),
                            ("validate", "Run standalone Python data-quality checks; no APIs or credentials")):
        cmd = commands.add_parser(name, help=help_text)
        cmd.add_argument("--config", type=Path, default=Path("configs/demo.yaml"))
        cmd.add_argument("--output-dir", type=Path, help="Override the configured output root")
        if name == "run":
            cmd.add_argument("--mode", choices=("fixtures", "live", "replay", "snapshots"))
            cmd.add_argument("--replay-from", type=Path, help="Existing successful live-run directory (not its database_ready subfolder)")
            cmd.add_argument("--fail-on-dq", action="store_true", help="Exit 2 after writing the bundle if input records were rejected")
    verify = commands.add_parser("verify-bundle", help="Verify checksums, types, keys, row counts and all foreign keys")
    verify.add_argument("directory", type=Path)
    schema = commands.add_parser("schema", help="Generate first-install SQL Server DDL")
    schema.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "schema":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(sql_ddl(), encoding="utf-8")
            print(json.dumps({"status": "GENERATED", "path": str(args.output)}))
            return 0
        if args.command == "verify-bundle":
            print(json.dumps(verify_bundle(args.directory), sort_keys=True))
            return 0
        result = run_pipeline(args.config, output_dir=args.output_dir, mode=getattr(args, "mode", None),
                              replay_from=getattr(args, "replay_from", None), validate_only=args.command == "validate",
                              emit=lambda event: print(json.dumps(event, sort_keys=True), flush=True))
        print(json.dumps({"status": result.status, "run_directory": str(result.run_dir),
                          "database_ready": str(result.bundle) if result.bundle else None}, sort_keys=True))
        return 2 if result.counts["rejected_records"] and (args.command == "validate" or getattr(args, "fail_on_dq", False)) else 0
    except PipelineError as exc:
        # All PipelineError messages are controlled, non-secret diagnostics from this codebase.
        print(json.dumps({"status": "FAILED", "error_type": type(exc).__name__, "message": str(exc)}), file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "FAILED", "error_type": type(exc).__name__,
                          "message": "Input, filesystem or source structure failed; inspect the failed run's stage and input contract."}), file=sys.stderr)
        return 1
    except Exception as exc:
        print(json.dumps({"status": "FAILED", "error_type": type(exc).__name__,
                          "message": "Unexpected failure; no request headers, source records or traceback are logged."}), file=sys.stderr)
        return 1
