"""Private training-only review lists and public aggregate model diagnostics.

Partial search estimates are conditional on the best evaluated numeric score.
An unsearched move may change that reference. The program never renormalizes
away unsearched probability mass, calls a model probability a human solve rate,
or lets validation/test positions enter the discovery rankings.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics

import chess

try:
    from scripts.mining_v2_engine import probability_summary, validated_policies
    from scripts.mining_v2_summary import (
        check_identity, check_policy_manifest, check_screen_manifest, index_records,
    )
except ModuleNotFoundError:  # Direct script invocation from the repository root.
    from mining_v2_engine import probability_summary, validated_policies
    from mining_v2_summary import (
        check_identity, check_policy_manifest, check_screen_manifest, index_records,
    )


ROOT = Path(__file__).resolve().parents[1]
RATING_PAIRS = ((1400, 1700), (1700, 2000), (2000, 2300))


def read(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(fen):
    return " ".join(chess.Board(fen).fen(en_passant="legal").split()[:4])


def exact_scores(scores):
    """Keep only reported point estimates, never a lower/upper-bound score."""
    usable = {}
    for move, score in scores.items():
        if (not score.get("score_is_exact", False)
                or score.get("lowerbound", False) or score.get("upperbound", False)):
            continue
        cp, mate = score.get("cp"), score.get("mate")
        if cp is not None and (isinstance(cp, bool) or not isinstance(cp, (int, float))
                               or not math.isfinite(cp)):
            continue
        if cp is None and (mate is None or isinstance(mate, bool)
                           or not isinstance(mate, int)):
            continue
        usable[move] = score
    return usable


def conditional_mass(scores, probabilities, tolerance=20):
    """Explicit conditional intervals, retaining all unknown move probability."""
    usable = exact_scores(scores)
    metric = probability_summary(usable, probabilities, tolerance, 300)
    if not metric.get("available"):
        return metric
    complete = set(usable) == set(probabilities)
    return {
        "available": True,
        "interpretation": "model mass within tolerance of the best observed numeric root score",
        "conditional_on_observed_reference": True,
        "all_legal_moves_have_point_scores": complete,
        "reference_cp": metric["reference_cp"], "tolerance_cp": tolerance,
        "observed_acceptable_moves": metric["acceptable"],
        "observed_acceptable_mass": metric["conditional_p_good_lower"],
        "unscored_mass": metric["unscored_mass"],
        "conditional_acceptable_mass_interval": [metric["conditional_p_good_lower"], metric["p_good_upper"]],
        "acceptable_mass_interval_allowing_unobserved_better_move": [metric["p_good_lower"], metric["p_good_upper"]],
        "conditional_capped_regret_interval_cp": [metric["capped_regret_lower_cp"], metric["conditional_capped_regret_upper_cp"]],
        "capped_regret_interval_allowing_unobserved_better_move_cp": [metric["capped_regret_lower_cp"], metric["capped_regret_upper_cp"]],
        "regret_cap_cp": 300,
        "searches_reached_target": all(score.get("reached_target", False) for score in usable.values()),
        "depth_range": [min((score.get("depth", 0) for score in usable.values()), default=0),
                        max((score.get("depth", 0) for score in usable.values()), default=0)],
        "verified_human_solve_probability": False,
    }


def difference_interval(after, before):
    return [after[0] - before[1], after[1] - before[0]]


def train_rankings(records, policies, screen, top_n=50, min_gain=.05, min_tv=.10):
    """Return private discovery lists; reject source/result split disagreement."""
    transitions, sensitivity = [], []
    eligible = 0
    for ident, record in records.items():
        if record.get("split") != "train":
            continue
        result = screen[ident]
        if result.get("split") != "train":
            raise ValueError(f"{ident}: source and screening splits disagree")
        if canonical(result["fen"]) != canonical(record["fen"]):
            raise ValueError(f"{ident}: source and screening positions disagree")
        legal = {move.uci() for move in chess.Board(record["fen"]).legal_moves}
        maps = validated_policies(record, policies[ident], legal)
        scores = result.get("scores", {})
        # Every discovery row uses the same score subset for every policy condition.
        if set(scores) - legal:
            raise ValueError(f"{ident}: illegal root move in screening scores")
        usable = exact_scores(scores)
        numeric = [score["cp"] for score in usable.values() if score.get("cp") is not None]
        if (not numeric or abs(max(numeric)) > 200
                or any(score.get("mate") is not None for score in scores.values())):
            continue
        eligible += 1
        common = {"id": ident, "fen": record["fen"], "game_id": record["game_id"],
                  "split": "train", "cohort": record.get("cohort", record.get("source", {}).get("cohort")),
                  "status": "exploratory_training_review_not_verified_human_difficulty"}
        masses = {name: conditional_mass(scores, probability) for name, probability in maps.items()}
        for low, high in RATING_PAIRS:
            lo, hi = (masses.get(f"maia3/history/{rating}") for rating in (low, high))
            if not lo or not hi or not lo.get("available") or not hi.get("available"):
                continue
            delta = difference_interval(hi["conditional_acceptable_mass_interval"],
                                        lo["conditional_acceptable_mass_interval"])
            if delta[0] < min_gain:
                continue
            transitions.append({**common, "rating_pair": [low, high], "condition": "history",
                "lower_rating": lo, "higher_rating": hi,
                "conditional_mass_gain_interval": delta,
                "conditional_regret_reduction_interval_cp": difference_interval(
                    lo["conditional_capped_regret_interval_cp"], hi["conditional_capped_regret_interval_cp"]),
                "ranking_note": "Lower end of conditional mass gain; unsearched root values can change the acceptable set."})
        for rating in (1700, 2000):
            h, f = (maps.get(f"maia3/{mode}/{rating}") for mode in ("history", "fen_only"))
            if not h or not f:
                continue
            tv = .5 * sum(abs(h[move] - f[move]) for move in legal)
            if tv < min_tv:
                continue
            hm, fm = (masses[f"maia3/{mode}/{rating}"] for mode in ("history", "fen_only"))
            if not hm.get("available") or not fm.get("available"):
                continue
            sensitivity.append({**common, "rating": rating, "total_variation": tv,
                "top_move_changed": max(h, key=h.get) != max(f, key=f.get),
                "history": hm, "fen_only": fm,
                "history_minus_fen_conditional_mass_interval": difference_interval(
                    hm["conditional_acceptable_mass_interval"], fm["conditional_acceptable_mass_interval"]),
                "ranking_note": "Total variation of the full legal policies; this is input sensitivity, not predictive accuracy."})
    transitions.sort(key=lambda row: (-row["conditional_mass_gain_interval"][0], row["id"], row["rating_pair"]))
    sensitivity.sort(key=lambda row: (-row["total_variation"], row["id"], row["rating"]))
    counts = {"source_training_n": sum(row.get("split") == "train" for row in records.values()),
              "competitive_training_point_score_n": eligible,
              "rating_transition_rows_before_limit": len(transitions),
              "rating_transition_unique_positions_before_limit": len({row["id"] for row in transitions}),
              "history_sensitive_rows_before_limit": len(sensitivity),
              "history_sensitive_unique_positions_before_limit": len({row["id"] for row in sensitivity})}
    return transitions[:top_n], sensitivity[:top_n], counts


def latest_complete_deep(result_dir):
    """Later completed failures supersede earlier successes; running files wait."""
    latest, fingerprints, ignored = {}, {}, 0
    for path in sorted(Path(result_dir).glob("*deep*.jsonl")):
        manifest_path = path.with_suffix(".manifest.json")
        if not manifest_path.exists():
            raise ValueError(f"Missing deep provenance: {path.name}")
        manifest = json.loads(manifest_path.read_text())
        if not manifest.get("complete"):
            ignored += 1
            continue
        rows = read(path)
        if any(row.get("mode") != "deep" for row in rows):
            raise ValueError(f"Non-deep rows in completed deep batch: {path.name}")
        settings = manifest["settings"]
        source_path, policy_path = (Path(settings[key]) for key in ("input", "policies"))
        if not source_path.is_absolute():
            source_path = ROOT / source_path
        if not policy_path.is_absolute():
            policy_path = ROOT / policy_path
        source = index_records(read(source_path), "Deep source")
        check_screen_manifest(manifest, source_path, policy_path, rows, source, path.name)
        fingerprints[path.name] = {"scores_sha256": sha(path), "manifest_sha256": sha(manifest_path)}
        stamp = (manifest.get("finished_at", 0), path.name)
        for row in rows:
            key = canonical(row["fen"])
            if key not in latest or stamp > latest[key][0]:
                latest[key] = (stamp, row)
    return {key: value[1] for key, value in latest.items()}, fingerprints, ignored


def complete_depth(scores, legal, expected_depth=None):
    usable = exact_scores(scores)
    return (set(usable) == legal and all(score.get("reached_target", False) for score in usable.values())
            and not any(score.get("mate") is not None for score in usable.values())
            and (expected_depth is None or all(score.get("depth", 0) >= expected_depth
                                              for score in usable.values())))


def compare_model_sizes(inputs, policies5, policies79, deep):
    """Calculate any-acceptable-move mass and capped regret at complete depths."""
    comparisons, excluded = [], Counter()
    for ident, record in inputs.items():
        if record.get("split") not in ("train", "discovery"):
            excluded["held_out"] += 1
            continue
        result = deep.get(canonical(record["fen"]))
        if result is None:
            excluded["no_completed_deep_record"] += 1
            continue
        if chess.Board(result["fen"]).fen() != chess.Board(record["fen"]).fen():
            excluded["latest_canonical_check_has_different_fen_counters"] += 1
            continue
        legal = {move.uci() for move in chess.Board(record["fen"]).legal_moves}
        if result.get("split") != record.get("split"):
            raise ValueError("Deep result split differs from model comparison source")
        p5 = validated_policies(record, policies5[ident], legal)
        p79 = validated_policies(record, policies79[ident], legal)
        item = {"id": ident, "fen": record["fen"], "split": record["split"],
                "game_id": record["game_id"], "audit_verified": bool(result.get("verified")),
                "preferred_condition": "history" if record.get("history_available", True) else "fen_only",
                "depths": {}, "interpretation": "Model sensitivity on an exploratory selected set; no human outcome inference."}
        for depth, scores in sorted(result.get("searches", {}).items(), key=lambda pair: int(pair[0])):
            if not complete_depth(scores, legal, int(depth)):
                excluded["depth_incomplete_bound_unreached_or_mate"] += 1
                continue
            conditions = {}
            for name in sorted(p5.keys() & p79.keys()):
                if not name.startswith("maia3/"):
                    continue
                conditions[name] = {}
                for tolerance in (20, 50):
                    m5, m79 = (probability_summary(scores, probs, tolerance, 300) for probs in (p5[name], p79[name]))
                    if not m5.get("available") or not m79.get("available"):
                        continue
                    conditions[name][str(tolerance)] = {
                        "acceptable_moves": m5["acceptable"], "reference_cp": m5["reference_cp"],
                        "all_legal_moves_scored": True, "regret_cap_cp": 300,
                        "maia3_5m": {"p_any_acceptable": m5["conditional_p_good_lower"],
                                      "capped_regret_cp": m5["capped_regret_lower_cp"]},
                        "maia3_79m": {"p_any_acceptable": m79["conditional_p_good_lower"],
                                       "capped_regret_cp": m79["capped_regret_lower_cp"]},
                        "delta_79m_minus_5m": {
                            "p_any_acceptable": m79["conditional_p_good_lower"] - m5["conditional_p_good_lower"],
                            "capped_regret_cp": m79["capped_regret_lower_cp"] - m5["capped_regret_lower_cp"]},
                    }
            item["depths"][depth] = conditions
        if item["depths"]:
            comparisons.append(item)
        else:
            excluded["no_complete_usable_depth"] += 1
    return comparisons, dict(excluded)


def stats(values):
    return {"n": len(values), "mean": statistics.mean(values) if values else None,
            "median": statistics.median(values) if values else None,
            "min": min(values) if values else None, "max": max(values) if values else None}


def heldout_exact_choice(records, policies, screen):
    """Fixed bins on the untouched test split; no fitting or discovery ranking."""
    boundaries = (0., .05, .20, .50, 1.)
    groups = {"all_test": [], "club_movers_1800_to_2000_test": []}
    for ident, record in records.items():
        if record.get("split") != "test":
            continue
        result = screen[ident]
        if result.get("split") != "test" or canonical(result["fen"]) != canonical(record["fen"]):
            raise ValueError("Held-out source and screening identity disagree")
        legal = {move.uci() for move in chess.Board(record["fen"]).legal_moves}
        maps = validated_policies(record, policies[ident], legal)
        policy = maps.get("maia3/history/2000")
        if policy is None:
            raise ValueError("Held-out exact-choice diagnostic requires the fixed history/2000 policy")
        target, actual = result.get("best"), record.get("played_move")
        if target not in legal or actual not in legal:
            raise ValueError("Held-out target and observed move must both be legal")
        observation = (policy[target], int(actual == target), record["game_id"])
        groups["all_test"].append(observation)
        rating = record.get("mover_elo")
        cohort = record.get("cohort", record.get("source", {}).get("cohort"))
        if cohort == "club" and rating is not None and 1800 <= rating <= 2000:
            groups["club_movers_1800_to_2000_test"].append(observation)
    summaries = {}
    for name, observations in groups.items():
        bins = []
        for index, (lower, upper) in enumerate(zip(boundaries, boundaries[1:])):
            members = [row for row in observations
                       if lower <= row[0] and (row[0] < upper or (index == 3 and row[0] <= upper))]
            games = len({row[2] for row in members})
            bins.append({"probability_lower_inclusive": lower, "probability_upper": upper,
                         "upper_inclusive": index == 3, "positions_n": len(members),
                         "source_games_n": games,
                         "mean_target_probability": statistics.mean(row[0] for row in members) if members else None,
                         "observed_exact_target_choice_rate": statistics.mean(row[1] for row in members) if members else None,
                         "sparse_fewer_than_30_games": games < 30, "descriptive_only": True})
        summaries[name] = {"positions_n": len(observations),
                          "source_games_n": len({row[2] for row in observations}), "bins": bins}
    return {"model": "Maia3-5M", "condition": "history", "self_rating": 2000,
            "opponent_rating": 2000, "target": "original finite-budget screening target; exact UCI move",
            "split": "test", "fit_performed": False, "groups": summaries,
            "interpretation": "Descriptive observed-game exact-choice check at a fixed hypothetical rating. The finite-engine target may have other acceptable alternatives. This is not puzzle calibration, P(any good move), or a human teaching result.",
            "dependence_note": "Positions can share a source game; bins with fewer than 30 distinct games are sparse. No uncertainty or calibration claim is inferred from these bins."}


def public_aggregate(transitions, sensitivity, ranking_counts, comparisons, excluded,
                     fingerprints, ignored_deep_batches, args, heldout=None):
    """Whitelist aggregate fields; never copy per-item fields into publication."""
    groups = defaultdict(list)
    for row in comparisons:
        # Keep history and FEN-only cohorts distinct, and report depth 24 only here.
        for rating in (1700, 2000):
            name = f"maia3/{row['preferred_condition']}/{rating}"
            for tolerance, values in row["depths"].get("24", {}).get(name, {}).items():
                groups[(row["preferred_condition"], rating, int(tolerance))].append(values)
    model_groups = []
    for (condition, rating, tolerance), values in sorted(groups.items()):
        model_groups.append({"depth": 24, "condition": condition, "rating": rating,
            "tolerance_cp": tolerance, "positions_n": len(values),
            "mean_p_any_acceptable_5m": statistics.mean(value["maia3_5m"]["p_any_acceptable"] for value in values),
            "mean_p_any_acceptable_79m": statistics.mean(value["maia3_79m"]["p_any_acceptable"] for value in values),
            "mean_capped_regret_cp_5m": statistics.mean(value["maia3_5m"]["capped_regret_cp"] for value in values),
            "mean_capped_regret_cp_79m": statistics.mean(value["maia3_79m"]["capped_regret_cp"] for value in values),
            "mean_absolute_p_any_change": statistics.mean(abs(value["delta_79m_minus_5m"]["p_any_acceptable"]) for value in values),
            "crosses_upward_point10_n": sum(value["maia3_5m"]["p_any_acceptable"] <= .10 < value["maia3_79m"]["p_any_acceptable"] for value in values),
            "crosses_downward_point10_n": sum(value["maia3_79m"]["p_any_acceptable"] <= .10 < value["maia3_5m"]["p_any_acceptable"] for value in values)})
    return {
        "schema_version": 1, "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": "Exploratory model diagnostics; no demonstrated human learning or calibrated human solve probabilities",
        "discovery_scope": "Only pilot training rows enter review rankings; model-size audit also includes historical discovery rows",
        "ranking_settings": {"top_n": args.top_n, "minimum_conditional_mass_gain": args.min_gain,
                             "minimum_history_total_variation": args.min_tv, "tolerance_cp": 20,
                             "rating_pairs": [list(pair) for pair in RATING_PAIRS], "regret_cap_cp": 300},
        "ranking_counts": {**ranking_counts, "published_item_identifiers_n": 0,
                           "rating_transition_rows_saved": len(transitions),
                           "history_sensitive_rows_saved": len(sensitivity)},
        "ranked_transition_conditional_gain_lower": stats([row["conditional_mass_gain_interval"][0] for row in transitions]),
        "ranked_history_total_variation": stats([row["total_variation"] for row in sensitivity]),
        "partial_score_note": "Rankings use observed acceptable-move mass. Unknown root values can change the reference; tail probability is retained and partial intervals are explicitly conditional.",
        "model_size_comparison": {"positions_with_complete_depth_n": len(comparisons),
            "audit_verified_positions_n": sum(row["audit_verified"] for row in comparisons),
            "exclusions": excluded, "incomplete_deep_batches_ignored_n": ignored_deep_batches,
            "depth24_groups": model_groups,
            "note": "Full legal policies share the same exhaustive point-score map at each reported depth. The shortlist is selected and small; differences are sensitivity checks, not model accuracy estimates."},
        "heldout_exact_choice_diagnostic": heldout,
        "source_sha256": fingerprints,
    }


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n" for row in rows))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top-n", type=int, default=50)
    parser.add_argument("--min-gain", type=float, default=.05)
    parser.add_argument("--min-tv", type=float, default=.10)
    parser.add_argument("--output", type=Path, default=ROOT / "results/mining_v2_diagnostics.json")
    args = parser.parse_args()
    if args.top_n < 1 or not 0 <= args.min_gain <= 1 or not 0 <= args.min_tv <= 1:
        parser.error("top-n must be positive and probability thresholds must be in [0, 1]")
    data, result_dir = ROOT / "data/mining_v2", ROOT / "results/mining_v2"
    input_path, policy_path, screen_path = data / "positions.jsonl", data / "policies.jsonl", result_dir / "pilot_screen.jsonl"
    records = index_records(read(input_path), "Pilot positions")
    policies = check_identity(read(policy_path), records, "Pilot policies")
    screening = check_identity(read(screen_path), records, "Pilot screening")
    pilot_policy_manifest = json.loads((data / "policy_manifest.json").read_text())
    check_policy_manifest(pilot_policy_manifest, input_path, policy_path, list(policies.values()), records)
    if pilot_policy_manifest.get("maia3", {}).get("model") != "Maia3-5M":
        raise ValueError("Pilot screening policies must come from Maia3-5M")
    check_screen_manifest(json.loads((result_dir / "pilot_screen.manifest.json").read_text()),
                          input_path, policy_path, list(screening.values()), records, "Pilot screening")
    transitions, sensitivity, counts = train_rankings(records, policies, screening, args.top_n, args.min_gain, args.min_tv)
    large_input, large_policy = data / "shortlist_79m.jsonl", data / "shortlist_79m_policies.jsonl"
    large_records = index_records(read(large_input), "79M shortlist")
    large_rows = read(large_policy)
    large_manifest = json.loads((data / "shortlist_79m_policy_manifest.json").read_text())
    check_policy_manifest(large_manifest, large_input, large_policy, large_rows, large_records)
    if large_manifest.get("maia3", {}).get("model") != "Maia3-79M":
        raise ValueError("Larger-model policies must have a matching Maia3-79M manifest")
    large_policies = index_records(large_rows, "79M policies")
    historical_input, historical_policy = data / "historical.jsonl", data / "historical_policies.jsonl"
    historical_records = index_records(read(historical_input), "Historical source")
    historical_rows = read(historical_policy)
    historical_manifest = json.loads((data / "historical_policy_manifest.json").read_text())
    check_policy_manifest(historical_manifest, historical_input, historical_policy, historical_rows, historical_records)
    if historical_manifest.get("maia3", {}).get("model") != "Maia3-5M":
        raise ValueError("Historical comparison policies must come from Maia3-5M")
    all5 = {**index_records(historical_rows, "Historical policies"), **policies}
    deep, deep_hashes, ignored = latest_complete_deep(result_dir)
    comparisons, excluded = compare_model_sizes(large_records, all5, large_policies, deep)
    fingerprints = {"pilot_positions": sha(input_path), "pilot_policies": sha(policy_path),
                    "pilot_screening": sha(screen_path), "historical_policies": sha(data / "historical_policies.jsonl"),
                    "larger_model_inputs": sha(large_input), "larger_model_policies": sha(large_policy),
                    "larger_model_manifest": sha(data / "shortlist_79m_policy_manifest.json"),
                    "diagnostic_script": sha(Path(__file__)), "completed_deep_batches": deep_hashes}
    private_outputs = {"rating_transitions": (data / "diagnostic_rating_transitions.jsonl", transitions),
                       "history_sensitive": (data / "diagnostic_history_sensitive.jsonl", sensitivity),
                       "model_size_comparison": (data / "diagnostic_model_size_comparison.jsonl", comparisons)}
    for label, (path, rows) in private_outputs.items():
        write_jsonl(path, rows)
        fingerprints["private_" + label] = sha(path)
    heldout = heldout_exact_choice(records, policies, screening)
    public = public_aggregate(transitions, sensitivity, counts, comparisons, excluded, fingerprints, ignored, args, heldout)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(public, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"transition_rows": len(transitions), "history_rows": len(sensitivity),
                      "model_size_positions": len(comparisons), "ignored_running_deep_batches": ignored,
                      "public_output": str(args.output)}))


if __name__ == "__main__":
    main()
