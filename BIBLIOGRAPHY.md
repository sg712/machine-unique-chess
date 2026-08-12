# Bibliography — interpretability of superhuman chess engines

## Core (the spine of this project)
- **Schut, Tomašev, McGrath, Hassabis, Paquet, Kim (PNAS 2025)** — *Bridging the human–AI knowledge gap: concept discovery and transfer in AlphaZero.* [arXiv:2310.16410](https://arxiv.org/abs/2310.16410) · `papers/schut2023-concept-discovery-transfer.pdf`
  Mines machine-unique concept vectors from AZ via convex optimization over MCTS rollouts; filters by teachability (97.6% cut) and novelty (spectral test vs human-game basis); teaches survivors to 4 GMs (2600–2800) via prototype positions only. Improvements: +42/+25/+16/+6 pp. Lead author Lisa Schut: Oxford OATML PhD → DeepMind, ex-Dutch Olympiad player.
- **McGrath, Kapishnikov, Tomašev, Pearce, Hassabis, Kim, Paquet, Kramnik (PNAS 2022)** — *Acquisition of chess knowledge in AlphaZero.* [arXiv:2111.09259](https://arxiv.org/abs/2111.09259) · `papers/mcgrath2021-acquisition-chess-knowledge.pdf`
  Probes AZ for ~human concepts; they exist and emerge in human-like order during training.
- **Jenner, Kapur, Georgiev, Allen, Emmons, Russell (NeurIPS 2024)** — *Evidence of learned look-ahead in a chess-playing neural network.* [arXiv:2406.00877](https://arxiv.org/abs/2406.00877) · `papers/jenner2024-learned-lookahead.pdf` · code: `models/leela-interp/`
  Leela's policy net represents future moves that causally drive current choices. THE reproducible entry point (open code + open weights).
- **Follow-ups (2025–26):** *Understanding the learned look-ahead behavior of chess neural networks* ([arXiv:2505.21552](https://arxiv.org/abs/2505.21552)); *The Algorithm Is Not the Behavior* ([arXiv:2508.21380](https://arxiv.org/abs/2508.21380)) — learned priors can override look-ahead.

## Human skill modeling (the instrument for the frontier question)
- **Maia-2 (NeurIPS 2024)** — unified skill-aware human-move model, Elo 1100–2000. [arXiv:2409.20553](https://arxiv.org/abs/2409.20553) · `models/maia2-repo/` · pip `maia2`
- **Maia-3 (2026)** — successor, recommended by CSSLab for new projects. [arXiv:2605.19091](https://arxiv.org/abs/2605.19091) · [HF models](https://huggingface.co/collections/UofTCSSLab/maia3) — TODO: evaluate switching experiment 01 to it.

## Motivation / efficacy context
- **Southwick et al. (Psychological Science 2026)** — *Not all practice is created equal* (N=44k chess.com players): lessons + game review ≈ 3.6× improvement/hour vs playing. The practice-material half of this project exists because of this result.
- **DecodeChess** — the lone commercial "explain the engine" product; translates into existing human vocabulary only. The gap this project targets is precisely what a translator cannot reach.

## Open weights / tooling
- **Leela Chess Zero** — open AZ reproduction; nets at lczero.org; `leela-interp` ships converted PyTorch policy nets.
- **Stockfish NNUE** — open weights, but a small eval net + search: useful as ground truth, not as a concept substrate. Local build: `models/stockfish-build/`.
- **AlphaZero itself: closed.** Everything here reproduces on Leela/Maia or uses the paper's published positions.
