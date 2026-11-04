"""Read-only desktop view of explicitly registered, local development experiments."""
import hashlib
import json
from pathlib import Path

from .paths import data_root


def registry():
    return data_root() / ".dev-team"


def read(path):
    return json.loads(path.read_text("utf-8"))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def inputs(folder, state):
    return {
        "base": state["base_sha"], "issue": digest(read(folder / "issue.json")),
        "contract": digest(read(folder / "draft-contract-0.json")),
        "plan": digest(state["acceptance_plan"]), "scope": state["execution_scope_sha256"],
        "version": state["version"], "rounds": state["max_rounds"], "calls": state["max_launches"],
        "dependencies": state["dependency_paths"], "https": state["openai_https"],
        "model": state.get("experiment_model"),
    }


def arm_summary(folder, expected):
    state = read(folder / "state.json")
    metrics_path = folder / "metrics.json"
    metrics = read(metrics_path) if metrics_path.exists() else {}
    current = metrics.get("cli_launches") == state["launches"] and metrics.get("status") == state["status"]
    tokens = metrics.get("reported_tokens") or {}
    rounds = state["rounds"]
    objective = rounds[-1].get("objective", {}) if rounds else {}
    timeline = [dict(stage=a["stage"], status=a["status"], round=a["round"],
                     note=a.get("gate_error") or a.get("error") or "") for a in state["attempts"]]
    for item, attempt in zip(timeline, state["attempts"]):
        if item["stage"] in {"requirements","verification_plan","verify","diagnose","scope_review","supervise","reflect","evaluator_review"}:
            directory = attempt["directory"]
            if Path(directory).name == directory:
                report = folder / directory / "result.json"
                if report.is_file():
                    result = read(report)
                    decision = result.get("decision")
                    if isinstance(decision, str):
                        item["decision"] = decision[:80]
                    if not item["note"]:
                        item["note"] = str(result.get("reason") or result.get("summary") or "")[:500]
                    if item["stage"] == "reflect":
                        for key in ("observations", "proposals", "validation_plan"):
                            values = result.get(key)
                            if isinstance(values, list):
                                item[key] = [v[:1000] for v in values[:5] if isinstance(v, str)]
    history = []
    by_round = {r["round"]: r for r in rounds}
    for item in timeline:
        history.append(item)
        if item["stage"] == "develop":
            result = by_round.get(item["round"], {}).get("objective")
            if result:
                failed = [c["name"] for c in result["checks"] if not c["passed"]]
                history.append(dict(stage="objective", round=item["round"], status=result["status"],
                                    note=", ".join(failed) or result.get("summary", "")[:500]))
    dispatch = folder / "improvement-dispatch.json"
    jobs = read(dispatch)["jobs"] if dispatch.is_file() else []
    maintenance = [dict(id=j["id"], status=j["status"]) for j in jobs
                   if j["status"] in {"adopted","running","blocked","exhausted"}]
    return dict(status=state["status"], stage=state["stage"], reason=state["reason"],
                matched=inputs(folder, state) == expected and state.get("contract_sha256") in (None, expected["contract"]),
                timeline=history, maintenance=maintenance, candidate=state.get("candidate_sha"), checks=[
                    dict(name=c["name"], passed=c["passed"], observed=c.get("observed"))
                    for c in objective.get("checks", [])], gate=objective.get("status"),
                calls=state["launches"], rework=max(0,sum(a["stage"]=="develop" for a in state["attempts"])-1),
                supplements=state["supplements_used"], uncached=metrics.get("uncached_input_tokens") if current else None,
                cached=tokens.get("cached_input_tokens") if current else None,
                output=tokens.get("output_tokens") if current else None, usage_complete=current and metrics.get("usage_complete", False))


def snapshot():
    rows = []
    for path in sorted(registry().glob("*.json"), key=lambda p:p.stat().st_mtime, reverse=True):
        try:
            entry = read(path)
            pair = Path(entry["folder"])
            arms = {name: arm_summary(pair / name, entry["inputs"]) for name in ("direct","workflow")}
            rows.append(dict(id=path.stem,title=entry["title"], version=entry["inputs"]["version"],
                             base=entry["inputs"]["base"], historical=entry["historical"], arms=arms,
                             accounting=entry.get("accounting", {})))
        except (OSError, ValueError, KeyError, TypeError) as error:
            rows.append(dict(id=path.stem, error=f"实验记录无法读取 · {type(error).__name__}"))
    return {"experiments": rows}
