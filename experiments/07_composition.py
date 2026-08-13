"""Exp 07 — are machine-unique positions composed of nameable human motifs?

Builds a direction in Leela's latent space for each named human motif (from
lichess puzzle theme tags), then asks how much of the machine-unique subset's
distinguishing direction is reconstructable from that motif basis.

High R^2 (vs control calibration) => machine concepts are compositions of human
primitives ("unnamed chunks"). Low R^2 => genuinely off-vocabulary.

Outputs: results/07_composition.json, cached embeddings in results/emb_cache/
"""
import io
import json
import pathlib
import sys
import urllib.request

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "models" / "leela-interp" / "src"))

THEMES = ["pin", "fork", "skewer", "discoveredAttack", "deflection", "attraction",
          "sacrifice", "quietMove", "defensiveMove", "clearance", "intermezzo", "exposedKing"]
PER_THEME = 150
PUZZLE_URL = "https://database.lichess.org/lichess_db_puzzle.csv.zst"


def collect_theme_positions() -> dict:
    """Stream the puzzle DB until every theme has PER_THEME positions.

    Puzzle FEN is the position BEFORE the opponent's setup move; the themed
    position arises after pushing the first move of `Moves`.
    """
    import chess
    import pyzstd
    out = {t: [] for t in THEMES}
    baseline = []
    req = urllib.request.Request(PUZZLE_URL, headers={"User-Agent": "unnamed-concepts research"})
    resp = urllib.request.urlopen(req, timeout=60)
    dctx = pyzstd.EndlessZstdDecompressor()
    buf = ""
    header_skipped = False
    done = False
    while not done:
        chunk = resp.read(1 << 20)
        if not chunk:
            break
        buf += dctx.decompress(chunk).decode("utf-8", errors="replace")
        lines = buf.split("\n")
        buf = lines.pop()
        for ln in lines:
            if not header_skipped:
                header_skipped = True
                continue
            parts = ln.split(",")
            if len(parts) < 8:
                continue
            fen, moves, themes = parts[1], parts[2], parts[7]
            tset = set(themes.split())
            wanted = [t for t in THEMES if t in tset and len(out[t]) < PER_THEME]
            need_baseline = len(baseline) < 400
            if not wanted and not need_baseline:
                continue
            try:
                board = chess.Board(fen)
                board.push(chess.Move.from_uci(moves.split()[0]))
                themed_fen = board.fen()
            except Exception:
                continue
            for t in wanted:
                out[t].append(themed_fen)
            if need_baseline:
                baseline.append(themed_fen)
            if all(len(out[t]) >= PER_THEME for t in THEMES) and len(baseline) >= 400:
                done = True
                break
    resp.close()
    for t in THEMES:
        print(f"  {t}: {len(out[t])}")
    return {"themes": out, "baseline": baseline}


def main() -> None:
    from leela_interp import Lc0Model
    spec_path = ROOT / "experiments" / "05_leela_concepts.py"
    import importlib.util
    spec = importlib.util.spec_from_file_location("exp05", spec_path)
    exp05 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exp05)

    cache = ROOT / "results" / "emb_cache"
    cache.mkdir(parents=True, exist_ok=True)

    tp_file = cache / "theme_positions.json"
    if tp_file.exists():
        tp = json.load(open(tp_file))
    else:
        print("collecting theme positions from lichess puzzle DB...")
        tp = collect_theme_positions()
        json.dump(tp, open(tp_file, "w"))

    model = Lc0Model(str(exp05.WEIGHTS), device="cpu")
    emb = exp05.Embedder(model, layer=10)

    def embed_set(name, fens):
        f = cache / f"{name}.npy"
        if f.exists():
            return np.load(f)
        Z = emb.embed(fens)
        np.save(f, Z)
        print(f"embedded {name}: {Z.shape}")
        return Z

    mu = pd.read_csv(ROOT / "results" / "master_machine_unique.csv")
    allpos = pd.read_csv(ROOT / "results" / "master_all.csv")
    control = allpos[~allpos.machine_unique].sample(400, random_state=0)

    Z_mu = embed_set("mu", mu.fen.tolist())
    Z_ctl = embed_set("control", control.fen.tolist())
    Z_base = embed_set("puzzle_baseline", tp["baseline"])
    theme_dirs, theme_names = [], []
    for t in THEMES:
        Zt = embed_set(f"theme_{t}", tp["themes"][t])
        theme_dirs.append(Zt.mean(0) - Z_base.mean(0))
        theme_names.append(t)
    B = np.stack(theme_dirs)                      # (T, d)
    ctl_mean = Z_ctl.mean(0)

    def r2_of(d):
        coef, res, *_ = np.linalg.lstsq(B.T, d, rcond=None)
        pred = B.T @ coef
        ss_res = float(((d - pred) ** 2).sum())
        ss_tot = float((d ** 2).sum())
        return 1 - ss_res / max(ss_tot, 1e-12), coef

    # global machine-unique direction
    d_mu = Z_mu.mean(0) - ctl_mean
    r2_global, coef_global = r2_of(d_mu)

    # per-position distributions (MU vs held-out control halves for calibration)
    r2_mu = [r2_of(z - ctl_mean)[0] for z in Z_mu]
    r2_ctl = [r2_of(z - Z_ctl[200:].mean(0))[0] for z in Z_ctl[:200]]

    out = {
        "themes": theme_names,
        "r2_global_mu_direction": r2_global,
        "coef_global": dict(zip(theme_names, np.round(coef_global, 4).tolist())),
        "r2_mu_per_position": {"mean": float(np.mean(r2_mu)), "median": float(np.median(r2_mu))},
        "r2_control_per_position": {"mean": float(np.mean(r2_ctl)), "median": float(np.median(r2_ctl))},
    }
    json.dump(out, open(ROOT / "results" / "07_composition.json", "w"), indent=2)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
