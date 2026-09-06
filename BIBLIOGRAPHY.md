# Bibliography and research foundations

Updated 7 September 2026. These sources motivate the project or supply its instruments. Their results are not evidence that this trainer improves chess strength.

- **Schut, Tomašev, McGrath, Hassabis, Paquet and Kim.** *Bridging the Human-AI Knowledge Gap: Concept Discovery and Transfer in AlphaZero.* [Primary paper](https://arxiv.org/abs/2310.16410). The study reports improvements on concept-prototype positions in four grandmasters. Our Leela adaptation changes the representation, rollout procedure and evaluation; it has not replicated the human learning result.
- **Tang et al.** *Maia-2: A Unified Model for Human-AI Alignment in Chess.* NeurIPS 2024. [Primary paper](https://arxiv.org/abs/2409.20553), [code](https://github.com/CSSLab/maia2). Supplies the skill-conditioned human-move model used by the main mining pipeline. Our four tested rating settings are an experimental choice, not a continuous evaluation of every rating.
- **CSSLab.** Maia-3. [Official code and model documentation](https://github.com/CSSLab/maia3). Used for the separate top-one/top-five ranking experiment through 2600, not the full 5,155-position filter.
- **Jenner et al.** *Evidence of Learned Look-Ahead in a Chess-Playing Neural Network.* [Primary paper](https://arxiv.org/abs/2406.00877), [interpretability code](https://github.com/HumanCompatibleAI/leela-interp). Provides background and open tooling for inspecting Leela representations. The present clustering analysis is not an activation-level causal replication.
- **Stockfish developers.** [Stockfish source](https://github.com/official-stockfish/Stockfish). Version 17.1 is the analysis reference; finite-depth evaluations are estimates, not exhaustive ground truth.
- **Leela Chess Zero contributors.** [Project](https://lczero.org/). The project uses an open network through the interpretability tooling; historical checkpoint provenance should be made more reproducible before a confirmatory study.
- **Lichess contributors.** [Game and puzzle databases](https://database.lichess.org/). Public games supply source positions and actual moves; puzzle tags supply the selected motif basis.
- **Lichess Elite Database.** [Archive](https://database.nikonoel.fr/). Supplies filtered elite games. Its time-control and date distribution differ from the club sample.

Earlier speculative literature notes and unverified product comparisons are retained in Git history. The current research claims and their limitations are documented in [methods](docs/METHODS.md).
