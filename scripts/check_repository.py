"""Lightweight repository guardrails; not a complete secret scanner or legal review."""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {".git", ".venv", "__pycache__", ".pytest_cache", "build", "dist", ".coverage"}
PRIVATE = {"private", "runs", "raw", "processed", "cache"}
SENSITIVE = re.compile(r"api[_-]?key|password|credential|secret|access[_-]?token", re.I)
TOKEN_PATTERNS = (re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"), re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"))


def candidates() -> list[Path]:
    if (ROOT / ".git").exists():
        result = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True)
        return [ROOT / name for name in result.stdout.decode().split("\x00") if name]
    return [p for p in ROOT.rglob("*") if p.is_file() and not set(p.relative_to(ROOT).parts) & EXCLUDED
            and not (p.relative_to(ROOT).parts[0] == "data" and set(p.relative_to(ROOT).parts[1:]) & PRIVATE)
            and not any(part.endswith(".egg-info") for part in p.parts)]


def inspect(path: Path) -> list[str]:
    rel = path.relative_to(ROOT)
    reasons = []
    if path.is_symlink():
        return ["symlink must be reviewed"]
    if (rel.parts[0] == "data" and set(rel.parts[1:]) & PRIVATE) or path.suffix.lower() in {".zip", ".gpkg", ".xlsx", ".pfx", ".pem", ".ipynb"}:
        reasons.append("private data, archive, notebook or key file must not be committed")
    if path.name.startswith(".env") and path.name != ".env.example":
        reasons.append("environment file must not be committed")
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeError, OSError):
        return reasons + ["unreviewed binary or unreadable file"]
    if any(pattern.search(text) for pattern in TOKEN_PATTERNS):
        reasons.append("possible credential material")
    if path.suffix == ".py":
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return reasons + ["Python syntax error"]
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                names = [child.id for target in targets for child in ast.walk(target) if isinstance(child, ast.Name)]
                value = node.value
                if (any(SENSITIVE.search(n) for n in names) and isinstance(value, ast.Constant)
                        and isinstance(value.value, str) and len(value.value) > 6):
                    if not (rel.parts[0] == "tests" and value.value.startswith("unit-test-only-")):
                        reasons.append("literal assigned to a sensitive variable")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"get", "getenv"} and len(node.args) >= 2:
                key, default = node.args[:2]
                if (isinstance(key, ast.Constant) and isinstance(key.value, str) and SENSITIVE.search(key.value)
                        and isinstance(default, ast.Constant) and isinstance(default.value, str) and default.value):
                    reasons.append("non-empty literal credential fallback")
    return sorted(set(reasons))


def main() -> int:
    files = candidates()
    problems = {str(p.relative_to(ROOT)): inspect(p) for p in files}
    problems = {name: reasons for name, reasons in problems.items() if reasons}
    for name, reasons in sorted(problems.items()):
        print(f"REVIEW {name}: {'; '.join(reasons)}")  # Never echo matching secret values.
    print(f"Repository checks: {len(files)} files, {len(problems)} files requiring review.")
    return int(bool(problems))


if __name__ == "__main__":
    raise SystemExit(main())
