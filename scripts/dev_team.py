"""Pair a single developer and the experimental workflow on one confirmed issue."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from desk_companion.development_team import digest, inputs, registry, snapshot
from . import dev_cycle as cycle


def register(pair, *, historical=False):
    pair = pair.resolve()
    states = [cycle.read(pair / name / "state.json") for name in ("direct", "workflow")]
    first, second = [inputs(pair / name, state) for name, state in zip(("direct","workflow"), states)]
    if first != second or not states[0]["acceptance_plan"]:
        raise ValueError("需求、起点、契约、资源额度或固定验收条件不一致")
    if historical and any(s["stage"] != "done" for s in states):
        raise ValueError("仅可导入已结束的历史对照")
    issue = cycle.read(pair / "workflow/issue.json")
    title = issue.get("title") or issue.get("text","").splitlines()[0]
    entry = dict(folder=str(pair), title=title, inputs=first, historical=historical)
    ident = digest(str(pair))[:16]
    path = registry() / (ident + ".json")
    if path.exists():
        saved = cycle.read(path)
        if any(saved.get(key) != value for key,value in entry.items()):
            raise ValueError("登记内容与既有实验不符")
        return ident
    path.parent.mkdir(parents=True, exist_ok=True)
    cycle.write(path, entry)
    return ident


def create(args):
    pair = args.pair.resolve()
    contract, plan = cycle.read(args.contract), cycle.read(args.plan)
    if not plan:
        raise ValueError("对照需要固定验收脚本，两组使用同一判定器")
    cycle.validate_plan(plan)
    issue = cycle.read(args.issue)
    if not isinstance(issue, dict) or not (issue.get("text") or issue.get("body")):
        raise ValueError("issue JSON 需要 text 或 body")
    pair.mkdir(parents=True, exist_ok=False)
    for name in ("direct","workflow"):
        folder = pair / name
        state = cycle.initialize(args.repo, folder, issue, confirmed_contract=contract,
                                 acceptance_plan=plan, dependency_paths=args.dependency_path,
                                 rounds=args.rounds, launches=args.max_launches, openai_https=args.openai_https)
        state["experiment_arm"] = name
        state["experiment_model"] = args.model
        state["max_acceptance_revisions"] = 0
        if name == "direct":
            state.update(stage="develop", round=1, contract=contract, contract_sha256=digest(contract))
            cycle.write(folder / "contract.json", contract)
        cycle.write(folder / "state.json", state)
    return register(pair)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--repo", type=Path, default=Path.cwd())
    for arg in ("pair","issue","contract","plan"):
        init.add_argument("--"+arg, type=Path, required=True)
    init.add_argument("--dependency-path", type=Path, action="append", default=[])
    init.add_argument("--openai-https", action="store_true")
    init.add_argument("--model", required=True, help="两组使用相同的 Codex 模型")
    init.add_argument("--rounds", type=int, default=3)
    init.add_argument("--max-launches", type=int, default=12)
    commands.add_parser("import-history").add_argument("pair", type=Path)
    commands.add_parser("status")
    account = commands.add_parser("account", help="登记某一组实测的额外人工与维护成本")
    account.add_argument("pair", type=Path)
    account.add_argument("arm", choices=("workflow","direct"))
    account.add_argument("--interventions", type=int, required=True)
    account.add_argument("--maintenance-tokens", type=int, required=True)
    for name in ("prepare","run"):
        command = commands.add_parser(name)
        command.add_argument("pair", type=Path)
        if name == "run":
            command.add_argument("--live", action="store_true", required=True)
        else:
            command.add_argument("--wheelhouse", type=Path)
            command.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    if args.command == "init":
        print(create(args))
    elif args.command == "import-history":
        print(register(args.pair, historical=True))
    elif args.command == "status":
        print(json.dumps(snapshot(), ensure_ascii=False, indent=2))
    elif args.command == "account":
        if min(args.interventions, args.maintenance_tokens) < 0:
            parser.error("成本不能为负数")
        pair = args.pair.resolve()
        entry_path = registry() / (digest(str(pair))[:16] + ".json")
        with cycle.locked(registry()):
            entry = cycle.read(entry_path)
            entry.setdefault("accounting", {})[args.arm] = dict(interventions=args.interventions,
                                                              maintenance_tokens=args.maintenance_tokens)
            cycle.write(entry_path, entry)
    else:
        pair = args.pair.resolve()
        entry = cycle.read(registry() / (digest(str(pair))[:16] + ".json"))
        if entry["historical"] or entry["folder"] != str(pair):
            raise ValueError("只有本机登记的新实验可运行")
        codes = []
        for name in ("direct","workflow"):
            folder = pair / name
            state = cycle.read(folder / "state.json")
            if inputs(folder,state) != entry["inputs"] or state["experiment_arm"] != name:
                raise ValueError("实验输入发生变化")
            if state["stage"] == "done":
                codes.append(int(state["status"] != "accepted"))
                continue
            argv = [sys.executable, str(Path(cycle.__file__)), args.command, str(folder)]
            if args.command == "run":
                argv.append("--live")
            else:
                if args.wheelhouse:
                    argv.extend(["--wheelhouse",str(args.wheelhouse)])
                if args.offline:
                    argv.append("--offline")
            codes.append(subprocess.call(argv))
        return int(any(codes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
