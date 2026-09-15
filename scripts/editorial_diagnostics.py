"""Aggregate-only exploratory diagnostics of frozen, editorial-eligible v3 evidence.

No engine searches, model inference, holdout tuning, or puzzle promotion occurs.
Every numeric diagnostic is conditional on the already selected retained pool.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import candidate_review as review

RATINGS = ("1400", "1700", "2000", "2300")
DEPTHS = ("20", "24")
SEED = "editorial-diagnostics-20260916"
SCOPE = ("Exploratory description of retained, editorial-eligible states only; not a population "
         "estimate, a held-out evaluation, human success measurement, or a trainer release. "
         "All originating observations must be recovered, have no BOT tag, not be known public, "
         "and have analysis roles confined to prior_development, pilot_train, and new_train.")


def summary(values):
    """Linear-interpolated empirical quantiles, without inferential intervals."""
    data = sorted(values)
    if not data or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in data):
        raise ValueError("Summary requires nonempty finite numeric observations")
    def quantile(fraction):
        where = fraction * (len(data) - 1)
        lower = math.floor(where)
        return data[lower] + (data[min(lower + 1, len(data) - 1)] - data[lower]) * (where - lower)
    return {"n": len(data), "min": min(data), "p10": quantile(.1), "p25": quantile(.25),
            "median": quantile(.5), "p75": quantile(.75), "p90": quantile(.9), "max": max(data),
            "mean": math.fsum(data) / len(data)}


def count_by(values):
    return dict(sorted(Counter(str(value) if value is not None else "unknown" for value in values).items()))


def numeric_rating_bin(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return "unknown"
    if value < 1800:
        return "under_1800"
    if value >= 2800:
        return "2800_plus"
    lower = int(value // 200) * 200
    return f"{lower}_{lower + 199}"


def root_scores_for(eligible, records, paths):
    """Read only eligible root scores into memory, never analyze holdout boards."""
    selected = set(eligible)
    scores = {key: {depth: {} for depth in DEPTHS} for key in selected}
    for name in ("imported_roots_sha256", "new_roots_sha256"):
        with paths[name].open() as source:
            for line in source:
                row = json.loads(line)
                key = row["record_id"]
                if key not in selected:
                    continue
                depth = str(row["target_depth"])
                if (depth not in DEPTHS or row.get("fen") != records[key]["fen"] or
                        row.get("board_context") != "fen_only" or row.get("score_is_exact") is not True or
                        row.get("reached_target") is not True or row.get("depth", -1) < int(depth) or
                        row.get("lowerbound") or row.get("upperbound") or row.get("mate") is not None):
                    raise ValueError("Selected root identity or numeric exact-depth evidence differs")
                move = row["uci"]
                cp = row.get("cp")
                if (move in scores[key][depth] or isinstance(cp, bool) or
                        not isinstance(cp, (int, float)) or not math.isfinite(cp)):
                    raise ValueError("Duplicate or nonfinite selected root score")
                scores[key][depth][move] = cp
    return scores


def position_diagnostics(outcome, policy, scores):
    """Reconcile saved roots/policies/outcomes, then calculate descriptive margins."""
    maps = policy.get("maia3", {}).get("fen_only", {})
    if policy.get("input_condition") != "fen_only" or set(maps) != set(RATINGS):
        raise ValueError("Expected the frozen four-rating FEN-only policy")
    if outcome.get("survives") is not True or outcome.get("trainer_ready") is not False:
        raise ValueError("Only retained, unpromoted evidence may be diagnosed")
    if set(scores) != set(DEPTHS) or set(scores["20"]) != set(scores["24"]):
        raise ValueError("Root coverage differs between depths")
    legal = set(scores["24"])
    if len(legal) != outcome["legal_count"] or not legal:
        raise ValueError("Selected legal-root coverage differs")
    for probs in maps.values():
        if (set(probs) != legal or any(isinstance(v, bool) or not isinstance(v, (int, float)) or
                not math.isfinite(v) or v < 0 or v > 1 for v in probs.values()) or
                abs(math.fsum(probs.values()) - 1) > 1e-5):
            raise ValueError("Selected policy is not a complete legal probability distribution")
    worst_p, min_regret, eval_margin = 0., math.inf, math.inf
    metrics, tolerances = {}, {}
    acceptance_boundary = []
    exact_ties = {}
    for depth in DEPTHS:
        numeric = scores[depth]
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in numeric.values()):
            raise ValueError("Nonfinite selected score")
        best = max(numeric.values())
        losses = {move: best - cp for move, cp in numeric.items()}
        accepted = sorted(move for move, loss in losses.items() if loss <= 20)
        exact = sorted(move for move, loss in losses.items() if loss == 0)
        if (accepted != outcome["accepted"][depth] or exact != outcome["best_moves"][depth] or
                best != outcome["best_cp"][depth]):
            raise ValueError("Selected root scores disagree with frozen outcome")
        exact_ties[depth] = len(exact)
        eval_margin = min(eval_margin, 200 - abs(best))
        acceptance_boundary.append(min(abs(loss - 20) for loss in losses.values()))
        metrics[depth], tolerances[depth] = {}, {}
        roots = {move: {"cp": cp, "mate": None} for move, cp in numeric.items()}
        for rating in RATINGS:
            computed = review.scorer.original.base.probability_summary(roots, maps[rating], 20)
            saved = outcome["metrics"][depth][f"maia3/fen_only/{rating}"]["20"]
            for field in ("p_good_lower", "p_good_upper", "capped_regret_lower_cp", "capped_regret_upper_cp"):
                if not math.isclose(computed[field], saved[field], rel_tol=1e-12, abs_tol=1e-10):
                    raise ValueError("Selected probability/regret differs from frozen outcome")
            exact_mass = math.fsum(maps[rating][move] for move in exact)
            good_mass = math.fsum(maps[rating][move] for move in accepted)
            metrics[depth][rating] = {"exact_top_tie_set_mass": exact_mass, "acceptable_set_mass": good_mass,
                                      "extra_acceptable_mass": good_mass - exact_mass,
                                      "p_good_upper": computed["p_good_upper"],
                                      "regret_lower_cp": computed["capped_regret_lower_cp"]}
            if rating in ("1700", "2000"):
                worst_p = max(worst_p, computed["p_good_upper"])
                min_regret = min(min_regret, computed["capped_regret_lower_cp"])
        for tolerance in (10, 20, 30, 50):
            accepted_at = sorted(move for move, loss in losses.items() if loss <= tolerance)
            probabilities = [review.scorer.original.base.probability_summary(roots, maps[rating], tolerance)
                             for rating in ("1700", "2000")]
            tolerances[depth][str(tolerance)] = {"accepted": accepted_at,
                "passes_probability_gate": all(row["p_good_upper"] <= .10 for row in probabilities)}
    if outcome["accepted"]["20"] != outcome["accepted"]["24"] or worst_p > .10 or min_regret < 50 or eval_margin < 0:
        raise ValueError("Retained outcome no longer satisfies the frozen criterion")
    return {"multiplicity": len(outcome["accepted"]["24"]), "exact_ties": exact_ties, "metrics": metrics,
            "max_p_good_upper": worst_p, "min_regret_lower_cp": min_regret, "eval_margin_cp": eval_margin,
            "acceptance_boundary_distance_cp": min(acceptance_boundary),
            "tolerance_sensitivity": {t: {
                "same_acceptable_set_both_depths": tolerances["20"][t]["accepted"] == tolerances["24"][t]["accepted"],
                "passes_probability_both_depths": all(tolerances[d][t]["passes_probability_gate"] for d in DEPTHS),
                "passes_jointly": tolerances["20"][t]["accepted"] == tolerances["24"][t]["accepted"] and
                    all(tolerances[d][t]["passes_probability_gate"] for d in DEPTHS)} for t in ("10", "20", "30", "50")}}


class UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, item):
        self.parent.setdefault(item, item)
        if self.parent[item] != item:
            self.parent[item] = self.find(self.parent[item])
        return self.parent[item]

    def union(self, left, right):
        left, right = self.find(left), self.find(right)
        if left != right:
            self.parent[max(left, right)] = min(left, right)


def source_concentration(eligible, origins):
    """Collapse recorded game aliases, count incidences, then greedy all-origin dedup."""
    aliases = UnionFind()
    for key in eligible:
        review.source_games(origins[key])
        for row in origins[key]:
            aliases.find(row["game_id"])
            if row.get("legacy_game_id"):
                aliases.union(row["game_id"], row["legacy_game_id"])
    games = {key: {aliases.find(row["game_id"]) for row in origins[key]} for key in eligible}
    by_game = defaultdict(set)
    for key, sources in games.items():
        for source in sources:
            by_game[source].add(key)
    incidence = sorted((len(keys) for keys in by_game.values()), reverse=True)
    total = sum(incidence)
    components = UnionFind()
    for keys in by_game.values():
        ordered = sorted(keys)
        for key in ordered:
            components.union(ordered[0], key)
    sizes = Counter(components.find(key) for key in eligible)
    rank = lambda key: (hashlib.sha256(f"{SEED}:{key}".encode()).hexdigest(), key)
    used, selected = set(), []
    for key in sorted(eligible, key=rank):
        if games[key].isdisjoint(used):
            selected.append(key)
            used.update(games[key])
    return {"positions_n": len(eligible), "unique_source_games_after_recorded_alias_collapse_n": len(by_game),
            "position_game_incidences_n": total, "positions_with_multiple_origin_games_n": sum(len(g) > 1 for g in games.values()),
            "source_game_positions_histogram": count_by(incidence), "max_positions_from_one_game_n": max(incidence),
            "top_10_games_share_of_incidences": sum(incidence[:10]) / total,
            "source_incidence_hhi": math.fsum((n / total) ** 2 for n in incidence),
            "overlap_components_n": len(sizes), "largest_overlap_component_positions_n": max(sizes.values()),
            "greedy_one_position_per_all_origin_game_n": len(selected),
            "greedy_removed_for_shared_source_n": len(eligible) - len(selected),
            "greedy_method": "Seeded SHA-256 ordering; accept only when every alias-collapsed originating game is unused. Not a maximum independent set.",
            "selected_identity_digest_sha256": hashlib.sha256(review.encoded(sorted(selected))).hexdigest()}, selected


def build_report(records, outcomes, manifest, policies, scores, fingerprints):
    eligible, pool_counts = review.editorial_pool(records, outcomes, manifest)
    if not eligible:
        raise ValueError("No editorial-eligible retained evidence")
    if set(scores) != set(eligible):
        raise ValueError("Diagnostics must contain exactly the editorial-eligible root subset")
    calculated = {}
    for key in eligible:
        if policies[key].get("id") != key or policies[key].get("fen") != records[key]["fen"]:
            raise ValueError("Selected policy identity differs")
        calculated[key] = position_diagnostics(outcomes[key], policies[key], scores[key])
    rows = list(calculated.values())
    source, dedup = source_concentration(eligible, manifest["canonical_origins_by_id"])
    metadata = {"side": count_by(records[k]["side_to_move"] for k in eligible),
        "phase": count_by(records[k].get("phase", "unknown") for k in eligible),
        "representative_analysis_role": count_by(records[k].get("analysis_role", "unknown") for k in eligible),
        "all_origin_role_combinations": count_by(" + ".join(sorted(manifest["state_provenance_by_id"][k]["analysis_roles"])) for k in eligible),
        "saved_representative_rating_bin": count_by(records[k].get("rating_bin", "unknown") for k in eligible),
        "representative_mover_elo_bin_recomputed": count_by(numeric_rating_bin(records[k].get("mover_elo")) for k in eligible),
        "representative_time_control_class": count_by(records[k].get("time_control_class", "unknown") for k in eligible),
        "side_by_phase": {side: count_by(records[k].get("phase", "unknown") for k in eligible if records[k]["side_to_move"] == side)
                          for side in ("white", "black")},
        "note": "Except for explicitly all-origin fields, metadata describes the retained representative observation. Unknowns are retained; model rating is not player rating."}
    sensitivity = {str(t): {field + "_n": sum(row["tolerance_sensitivity"][str(t)][field] for row in rows)
                           for field in ("same_acceptable_set_both_depths", "passes_probability_both_depths", "passes_jointly")}
                   for t in (10, 20, 30, 50)}
    threshold = {"max_p_good_upper_across_two_depths_and_1700_2000": summary([r["max_p_good_upper"] for r in rows]),
        "min_regret_lower_cp_across_two_depths_and_1700_2000": summary([r["min_regret_lower_cp"] for r in rows]),
        "min_distance_from_plus_minus_200cp_boundary": summary([r["eval_margin_cp"] for r in rows]),
        "within_one_percentage_point_of_probability_cutoff_n": sum(.10 - r["max_p_good_upper"] <= .01 for r in rows),
        "within_two_percentage_points_of_probability_cutoff_n": sum(.10 - r["max_p_good_upper"] <= .02 for r in rows),
        "within_10cp_of_regret_cutoff_n": sum(r["min_regret_lower_cp"] - 50 <= 10 for r in rows),
        "within_25cp_of_regret_cutoff_n": sum(r["min_regret_lower_cp"] - 50 <= 25 for r in rows),
        "within_25cp_of_evaluation_boundary_n": sum(r["eval_margin_cp"] <= 25 for r in rows),
        "any_of_probability_1pp_regret_10cp_evaluation_25cp_margins_n": sum(
            .10 - r["max_p_good_upper"] <= .01 or r["min_regret_lower_cp"] - 50 <= 10 or r["eval_margin_cp"] <= 25 for r in rows),
        "hypothetical_probability_008_remaining_n": sum(r["max_p_good_upper"] <= .08 for r in rows),
        "hypothetical_probability_005_remaining_n": sum(r["max_p_good_upper"] <= .05 for r in rows),
        "hypothetical_regret_75cp_remaining_n": sum(r["min_regret_lower_cp"] >= 75 for r in rows),
        "hypothetical_abs_evaluation_150cp_remaining_n": sum(r["eval_margin_cp"] >= 50 for r in rows),
        "hypothetical_all_three_stricter_conditions_remaining_n": sum(
            r["max_p_good_upper"] <= .05 and r["min_regret_lower_cp"] >= 75 and r["eval_margin_cp"] >= 50 for r in rows),
        "note": "Post-selection sensitivity on saved fixed-depth scores. These are not new acceptance rules or evidence of human difficulty."}
    exact = {rating: {field: summary([r["metrics"]["24"][rating][field] for r in rows])
                     for field in ("exact_top_tie_set_mass", "acceptable_set_mass", "extra_acceptable_mass")}
             for rating in RATINGS}
    for rating in RATINGS:
        exact[rating]["extra_acceptable_mass_at_least_one_percentage_point_n"] = sum(r["metrics"]["24"][rating]["extra_acceptable_mass"] >= .01 for r in rows)
        exact[rating]["acceptable_mass_at_least_double_exact_top_tie_mass_n"] = sum(
            r["metrics"]["24"][rating]["extra_acceptable_mass"] > 1e-12 and
            r["metrics"]["24"][rating]["acceptable_set_mass"] >= 2 * r["metrics"]["24"][rating]["exact_top_tie_set_mass"] for r in rows)
    paired = sum(set(policies[k].get("maia3", {}).get("history", {})) == set(RATINGS) for k in eligible)
    if any(policies[k].get("maia3", {}).get("history") != {} for k in eligible):
        raise ValueError("New history evidence requires an explicit compatible-context analysis, not this FEN-only diagnostic")
    report = {"schema_version": 1, "date": "2026-09-16", "scope": SCOPE,
        "selection_seed": SEED, "pool_counts": pool_counts,
        "fingerprints": {**fingerprints, "diagnostics_builder_sha256": review.digest(__file__),
            "selection_builder_sha256": review.digest(review.selection.__file__),
            "editorial_identity_digest_sha256": hashlib.sha256(review.encoded(sorted(eligible))).hexdigest()},
        "metadata": metadata, "source_concentration": source,
        "deduplicated_side": count_by(records[k]["side_to_move"] for k in dedup),
        "deduplicated_phase": count_by(records[k].get("phase", "unknown") for k in dedup),
        "acceptable_set": {"depth24_size_histogram": count_by(r["multiplicity"] for r in rows),
            "multiple_acceptable_moves_n": sum(r["multiplicity"] > 1 for r in rows),
            "depth24_exact_top_score_tie_size_histogram": count_by(r["exact_ties"]["24"] for r in rows),
            "nearest_root_loss_distance_from_20cp_acceptance_boundary": summary([r["acceptance_boundary_distance_cp"] for r in rows]),
            "root_within_5cp_of_acceptance_boundary_at_either_depth_n": sum(r["acceptance_boundary_distance_cp"] <= 5 for r in rows),
            "tolerance_counterfactual_cp": sensitivity,
            "note": "The exact-top set includes every tied top score, not an arbitrary single best move. Tolerance sensitivity still uses saved depth20/24 scores and leaves regret/evaluation gates fixed."},
        "depth24_policy_probability": exact, "threshold_margins": threshold,
        "history_context": {"editorial_positions_n": len(eligible), "four_rating_history_maps_available_n": paired,
            "compatible_paired_context_comparison_available": False,
            "reason": "All eligible saved policy rows have empty history maps. Recovered source history does not imply a saved history-conditioned prediction."},
        "validation": {"frozen_source_hashes_checked": True, "only_editorial_roles_analyzed": True,
            "eligible_root_scores_and_metrics_reconciled": True, "new_engine_searches_n": 0,
            "new_model_predictions_n": 0, "trainer_positions_promoted_n": 0},
        "limitations": ["Conditioning on screening and retention prevents estimates of general chess prevalence or model calibration.",
            "Depth agreement is search stability, not a proof of chess truth or teaching value.",
            "Any-origin exclusions protect untouched validation/test roles; prior development remains exploratory even if an old split label says test or validation.",
            "Known-public filtering does not establish that the source games or positions have never been seen.",
            "Saved engine scores are FEN-only. No claims about repetition-history equivalence or human success are supported.",
            "Greedy source deduplication is deterministic but is neither optimal nor a balanced sample.",
            "Cross-side, phase, rating and policy comparisons are descriptive within this selected pool, with no significance tests."]}
    assert_aggregate_only(report)
    return report


def assert_aggregate_only(value):
    forbidden = {"fen", "uci", "san", "pv", "game_id", "legacy_game_id", "record_id", "origins", "path", "selected_ids", "items"}
    if isinstance(value, dict):
        if forbidden & set(value):
            raise ValueError("Public aggregate contains a private evidence field")
        for child in value.values():
            assert_aggregate_only(child)
    elif isinstance(value, list):
        for child in value:
            assert_aggregate_only(child)
    elif isinstance(value, str) and ("/Users/" in value or "file://" in value):
        raise ValueError("Public aggregate contains a private path")


def write_report(path, report, root=ROOT):
    path, root = Path(path), Path(root).resolve()
    if path.is_symlink() or path.resolve().parent != root / "results" or not path.name.startswith("editorial_diagnostics_") or path.suffix != ".json":
        raise ValueError("Output must be an editorial_diagnostics_*.json aggregate in results")
    assert_aggregate_only(report)
    payload = review.encoded(report)
    if path.exists():
        if path.read_bytes() == payload:
            return
        raise FileExistsError("Refusing to overwrite different diagnostic evidence")
    with path.open("xb") as target:
        target.write(payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "results/editorial_diagnostics_20260916.json")
    args = parser.parse_args()
    records, outcomes, manifest, paths, fingerprints, _ = review.verify_bundle()
    eligible, _ = review.editorial_pool(records, outcomes, manifest)
    policies = review.load_rows(paths["policy_sha256"])
    scores = root_scores_for(eligible, records, paths)
    report = build_report(records, outcomes, manifest, policies, scores, fingerprints)
    write_report(args.output, report)
    print(json.dumps({"editorial_positions_n": len(eligible), "new_engine_searches_n": 0,
                      "aggregate_sha256": review.digest(args.output)}, sort_keys=True))


if __name__ == "__main__":
    main()
