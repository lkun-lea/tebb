"""Run the pinned Pi compatibility probe with synthetic inputs and explicit live opt-in."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def inventory():
    imports = []
    for path in sorted((ROOT / "desk_companion").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            modules = ([node.module] if isinstance(node, ast.ImportFrom)
                       else [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
            for module in modules:
                if module and (module == "atlas" or module.startswith("atlas.")):
                    imports.append(dict(path=path.relative_to(ROOT).as_posix(), line=node.lineno, module=module))
    return imports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="A new JSON output file")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--profile", type=Path, help="Existing model configuration, read only")
    parser.add_argument("--case", dest="case_filter", help="Run one named live case")
    parser.add_argument("--effort", choices=("low", "high", "max"), default="low")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists. Preserve the original run and choose another file.")
    if args.live and not args.profile:
        parser.error("--live requires --profile")
    mode = "live" if args.live else "offline"
    payload = {}
    if args.live:
        config = json.loads((args.profile / "models.json").read_text(encoding="utf-8"))
        network_path = args.profile / "model-network.json"
        network = json.loads(network_path.read_text(encoding="utf-8")) if network_path.exists() else dict(mode="system")
        if network.get("mode") != "direct":
            parser.error("This bounded live batch currently validates the configured direct route only.")
        models = config.get("items", [])
        if not 1 <= len(models) <= 2:
            parser.error("This batch permits one or two configured models.")
        payload = dict(models=[{key: row[key] for key in ("model", "base_url", "api_key")} for row in models],
                       network=dict(mode="direct"), caseFilter=args.case_filter, effort=args.effort)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    command = [str(args.node.resolve()), str(Path(__file__).with_name("probe.mjs")), mode, str(args.output.resolve())]
    result = subprocess.run(command, input=json.dumps(payload), text=True, encoding="utf-8",
                            capture_output=True, cwd=Path(__file__).parent, timeout=330,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if not result.stdout:
        raise RuntimeError("Node probe produced no report. Check the pinned runtime and npm ci prerequisites.")
    report = json.loads(result.stdout)
    report.update(baseline=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                  probe_sha256=hashlib.sha256(Path(__file__).with_name("probe.mjs").read_bytes()).hexdigest(),
                  atlas_imports=inventory())
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for case in report["cases"]:
        print(json.dumps({key: case[key] for key in ("id", "status", "error") if key in case}, ensure_ascii=False))
    print(json.dumps(dict(passed=report["passed"], failed=report["failed"], output=str(args.output))))
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
