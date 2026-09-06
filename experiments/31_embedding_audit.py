"""Rerun only exp 20A with PCA fitted inside each training fold.

Preserves the historical exp 20 JSON and all production difficulty predictions.
Usage: OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 python experiments/31_embedding_audit.py
"""
import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("difficulty", ROOT / "experiments/20_difficulty_model.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

if __name__ == "__main__":
    result = {"generated_at": datetime.now(timezone.utc).isoformat(),
              "inputs": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in [ROOT / "results/16_mu_families.csv", ROOT / "results/emb_cache/mu_all.npy"]},
              "part_a": module.part_a()}
    (ROOT / "results/31_embedding_audit.json").write_text(json.dumps(result, indent=2) + "\n")
