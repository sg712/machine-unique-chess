#!/usr/bin/env bash
# Fetch the engines and networks this project depends on. None are committed:
# together they are ~1.3 GB, and all are freely redistributable from source.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p models

echo "==> Stockfish (engine used for ground truth)"
if [ ! -x models/stockfish-build/src/stockfish ]; then
  git clone --depth 1 https://github.com/official-stockfish/Stockfish models/stockfish-build
  ( cd models/stockfish-build/src && make -j build ARCH=apple-silicon )
fi

echo "==> Maia (human-behaviour model) — downloads its own weights on first use"
pip install -q maia2

echo "==> Leela Chess Zero interpretability tooling (optional: concept clustering only)"
[ -d models/leela-interp ] || git clone --depth 1 https://github.com/HumanCompatibleAI/leela-interp models/leela-interp
echo "    Leela weights: see models/leela-interp README (figshare download, ~360 MB)"

echo
echo "Done. The trainer itself needs none of the above — it serves precomputed"
echo "positions from webapp/concepts.json. These are only needed to re-run the pipeline."
