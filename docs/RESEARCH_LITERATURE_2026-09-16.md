# Research literature audit — 16 September 2026

The next useful contribution is a defensible connection between **engine–human-model disagreement, an understandable lesson, and later unaided performance**. A larger disagreement corpus alone does not establish that connection. This review separates those three claims and identifies experiments that can fail usefully.

## Scope and evidence standard

This is a targeted primary-source review, not a systematic review or an exhaustive claim of novelty. Searches covered human move prediction, chess concept transfer, neural representations, explanation accuracy, and human learning with AI, emphasizing 2024–2026. Paper identities and versions were checked on 16 September 2026. Full papers were inspected where available. The two Poulidis working papers were accessible as author-posted abstracts and indexed SSRN records; their full texts were not accessible in this session. Their findings below are consequently provisional and do not substitute for a methods audit.

Project context: [methods](METHODS.md), [completed depth checks](MINING_V3_FULL_DEEP.md), and [private candidate review workflow](CANDIDATE_REVIEW.md). The completed research has 1,398 retained candidates, but no new candidate has passed every trainer-release gate. Literature findings do not alter frozen selections, engine outcomes, or the live trainer.

“Human learning” below means people were evaluated after an intervention. Human-move prediction, annotator ratings of explanations, neural probe accuracy, and improvement of a model are different outcomes.

## Twelve sources that change the research plan

### 1. Concept transfer is plausible, but its strongest direct precedent is small

**Schut, Tomašev, McGrath, Hassabis, Paquet and Kim.** *Bridging the human–AI knowledge gap through concept discovery and transfer in AlphaZero.* PNAS 122(13), e2406675122, published online 26 March 2025. [Journal DOI](https://doi.org/10.1073/pnas.2406675122); [2023 full preprint, §6 and §8.8](https://arxiv.org/html/2310.16410v1); [publication metadata](https://pubmed.ncbi.nlm.nih.gov/40138346/).

- **Evidence/sample:** Four grandmasters received concept prototypes, studied AlphaZero continuations, then solved unseen prototypes from those concepts. The preprint describes four puzzles per concept at each stage, 3–4 concepts per player, and 36–48 presentations per player across stages. All four improved overall; some concept-level examples did not transfer.
- **Limit:** Preliminary, highly selected expert sample; no randomized active-control comparison or demonstrated tournament-rating gain. AI-to-AI teachability filtering is distinct from the subsequent human experiment.
- **Project implication:** Preserve the attempt → explanation → new-position sequence. Compare related-example teaching against a matched alternative and measure delayed transfer. Our different engine, representations, and failed sparse-direction transfer make this inspiration, not replication.
- **Evidence class:** Direct but small human-learning proof of concept.

### 2. Unlimited answer access may reduce learning

**Poulidis, Hamsa Bastani and Osbert Bastani.** *Self-Regulated AI Use Hinders Long-Term Learning.* Working paper, posted 16 October 2025; SSRN revision 1 August 2026. [Paper record](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5604932); [author’s abstract](https://stefanospoulidis.github.io/#research).

- **Evidence/sample:** The authors describe a randomized, 12-week field experiment with over 200 chess-club students. Both conditions received system-triggered assistance; one additionally allowed help on demand. The latter group reportedly gained less.
- **Limit:** Full methods, outcome scale, attrition, and uncertainty were not independently inspected here. The abstract’s percentage gains should not be repeated as Elo improvements. Reported mediation is not a separately randomized mechanism. This comparison does not establish that all hints are harmful or that withholding help always works.
- **Project implication:** Test an attempt-first, staged-hint policy. Record help exposure separately from unaided answers. Make unassisted, unseen-position performance the endpoint rather than successful completion with help.
- **Evidence class:** Direct randomized human-learning evidence, currently a working paper; abstract-level verification in this review.

### 3. Teaching the next decision matters as much as showing the first move

**Poulidis, Ge, Hamsa Bastani and Osbert Bastani.** *Action vs. Attention Signals for Human-AI Collaboration: Evidence from Chess.* Working paper, posted 10 February 2025; SSRN revision 10 July 2025. [Paper record](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5128584); [author’s abstract](https://stefanospoulidis.github.io/#research).

- **Evidence:** In a chess behavioral experiment, the authors report that warning players of an important decision retains a substantial fraction of the benefit of recommending the move. Recommended moves can leave players less prepared for subsequent decisions, whereas attention signals can help those later decisions too.
- **Sample/access:** The primary abstract does not state the sample size. This review does not import a number from secondary mirrors.
- **Limit:** Immediate sequential decision quality is not evidence of retained learning. The study’s warning signal is not identical to a concept hint in a puzzle.
- **Project implication:** Add an experimental continuation question after the engine move: “What is your plan after this reply?” Compare a position-specific hint with revealing the answer, while keeping task time comparable.
- **Evidence class:** Human decision-making experiment; not a long-term transfer result.

### 4. Maia-2 is a behavioral instrument, not a calibrated learner model

**Tang, Jiao, McIlroy-Young, Kleinberg, Sen and Anderson.** *Maia-2: A Unified Model for Human-AI Alignment in Chess.* NeurIPS 2024; arXiv v2, 31 October 2024. [Paper, §4](https://arxiv.org/html/2409.20553v2); [official code](https://github.com/CSSLab/maia2).

- **Evidence/sample:** The paper trains on 169 million rapid games/9.1 billion positions and reports 53.25% macro-averaged top-one accuracy on its established Maia benchmark, with additional cross-skill and 450,000-position grounded tests. It conditions on both players’ ratings.
- **Limit:** Better move matching and smoother rating-conditioned predictions do not validate a 5% probability threshold on a selected tail of surprising engine moves. A population at one rating is not the same as one person before and after training.
- **Project implication:** Evaluate held-out likelihood and calibration of total probability on acceptable moves; stratify by phase, source, side, and time control. Compare actual opponent rating against the equal-rating counterfactual explicitly. Retain the original instrument for historical comparability.
- **Evidence class:** Model prediction; no trainer efficacy result.

### 5. Maia-3 makes real history an essential sensitivity analysis

**Monroe, Eilender, Chalmers, Tang and Anderson.** *Chessformer: A Unified Architecture for Chess Modeling.* ICLR 2026; arXiv v1, 18 May 2026. [Paper, §4](https://arxiv.org/html/2605.19091v1); [official Maia-3 code](https://github.com/CSSLab/maia3).

- **Evidence/sample:** Maia-3-79M reports 57.1% move matching on 884,049 Allie blitz-test positions. The main model consumes the current board and seven past boards; history ablations improve from zero to seven past boards. Training uses January 2023–July 2025 blitz games, while the reference test samples 2022.
- **Limit:** This is not a temporally forward generalization test. Its benchmark excludes openings and low-clock states. Accuracy does not establish calibration on isolated research puzzles; FEN-only evaluation is not the reported full-history condition.
- **Project implication:** Keep genuine-history, missing-history, and FEN-only predictions separate. Cross-model agreement is a robustness diagnostic, not independent human validation, since models share Lichess-derived data and objectives.
- **Evidence class:** Model prediction and architectural analysis.

### 6. Clock-aware prediction is a useful additional stress test

**Thomas Johnson.** *ChessMimic: Per-Rating Transformer Models for Human Move, Clock, and Outcome Prediction in Online Blitz Chess.* Preprint v1, 3 June 2026. [Paper, §5 and §7](https://arxiv.org/html/2606.04473v1); [author’s code](https://github.com/thomasj02/1e4_ai).

- **Evidence/sample:** On 4,775,033 bot-filtered April 2026 blitz positions, one sampled ply per game, top-one move prediction is 56.23% versus 52.60% for Maia-2 blitz. Separate models include ratings, history, and clocks. The paper also directly compares Maia-3 sizes.
- **Limit:** It does not isolate the causal benefit of each design choice through controlled retraining. Its outcome-model calibration is not calibration of the move policy. Blitz, repeated players, and historical clock context differ from deliberate puzzle solving.
- **Project implication:** Candidate disagreements that disappear with history/clock context belong in a “context-sensitive” analysis. Start with a small diagnostic benchmark; do not replace the frozen Maia criterion or infer that this instrument is universally superior.
- **Evidence class:** Model benchmark, preprint; no human-learning result.

### 7. “Always difficult” and “teachable next” are different mining objectives

**Inamdar, Tang, Anderson and Zemel.** *Level Up: Defining and Exploiting Transitional Problems for Curriculum Learning.* Preprint v2, 3 June 2026; first posted 14 March. [Paper, §5 and Table 3](https://arxiv.org/html/2603.13761v2).

- **Evidence/sample:** The chess experiments train a weak Maia-2 setting on competence-ordered positions/puzzles. Table 3 lists 180,000 retained training problems for each chess setting, 20,000 per level. Ascending transitional curricula outperform alternatives in the reported model experiments; game-position-to-puzzle transfer is also tested.
- **Limit:** The learners are models. A rating-conditioned policy series is not a longitudinal human learning trajectory. Monotonic model success does not itself establish a human’s learning readiness.
- **Project implication:** Preserve the rare-at-every-rating research pool, but create a separate prospective comparison pool where acceptable-move probability increases with rating. Do not relabel this as validated personalized difficulty or quietly change the original mining definition.
- **Evidence class:** Machine-learning curriculum results, not human learning.

### 8. Causal interventions provide stronger evidence than embedding clusters

**Jenner, Kapur, Georgiev, Allen, Emmons and Russell.** *Evidence of Learned Look-Ahead in a Chess-Playing Neural Network.* Preprint, 2 June 2024. [Paper, §2–3](https://arxiv.org/html/2406.00877v1); [official tooling](https://github.com/HumanCompatibleAI/leela-interp).

- **Evidence/sample:** From roughly 900,000 puzzles, filtering retains 22,500 that the stronger policy solves and a weaker network does not. Activation patching, attention analysis, and probes support internal look-ahead. The famous 92% figure concerns predicting the third-ply target square in this restricted setting.
- **Limit:** Sacrifice patterns are overrepresented, and the existence of a mechanism on selected positions does not describe every decision. A probe’s success alone is not causal evidence; the intervention work matters.
- **Project implication:** For a small future mechanistic study, preregister predicted move-specific effects, compare relevant and control interventions, and retain per-square information. Our mean-pooled cluster labels do not already satisfy this standard.
- **Evidence class:** Model-mechanism evidence; no teaching experiment.

### 9. Sparse chess features are promising, but expensive and architecture-specific

**Lin et al.** *Tracing the Thought of a Grandmaster-level Chess-Playing Transformer.* Preprint v1, 11 April 2026. [Paper, §2, §5 and §7](https://arxiv.org/html/2604.10158v1); [official code](https://github.com/JacklE0niden/Leela-SAEs).

- **Evidence/sample:** Transcoders and sparse attention replacements analyze LC0 BT4, trained on 800 million square tokens with 100 million for analysis. Three chess players assess feature interpretations. A layer-wise analysis uses 1,000 random positions; feature steering tests move-specific pathways.
- **Limit:** One architecture; replacement fidelity, feature splitting, and interpretation remain limitations. Annotators judging a feature are not learners demonstrating transfer, and a causal model intervention is not a human cognitive mechanism.
- **Project implication:** Treat sparse decomposition as a later, separate hypothesis-driven project. First verify a reproducible checkpoint and useful teaching cases. Reusing released tools does not justify claiming we have discovered an engine’s reasoning.
- **Evidence class:** Model-mechanism and interpretation analysis, preprint.

### 10. A failed concept probe does not prove an “alien” chess concept

**Lomasov et al.** *Exploring Human-AI Conceptual Alignment through the Prism of Chess.* Preprint v1, 29 October 2025. [Paper, §3–4](https://arxiv.org/html/2510.26025v1); [author code/data](https://github.com/slomasov/ChessConceptsLLM).

- **Evidence/sample:** A 270M-parameter chess transformer is probed using Strategic Test Suite positions and 240 expert-annotated Chess960 positions across six concepts. Concept decoding changes across layers and weakens under the reported distribution shift.
- **Limit:** The authors’ broad interpretation about memorization is stronger than the narrow observation of probe-transfer failure. Distribution shift, probe capacity, representation format, and label construction are competing explanations. A six-concept basis cannot exhaust human chess understanding.
- **Project implication:** Include negative/control concepts, held-out position families, and alternative representation layers. Treat residual embedding variance as unexplained variance, not proof of new knowledge. Chess960 can later be a robustness task, not a substitute for the current standard-chess study.
- **Evidence class:** Exploratory representation analysis, preprint.

### 11. Fluent engine-assisted commentary still needs factual auditing

**Kim, Goh, Hwang, Cho and Ok.** *Bridging the Gap between Expert and Language Models: Concept-guided Chess Commentary Generation and Evaluation.* NAACL 2025, pp. 9497–9516, April 2025. [Paper and metadata](https://aclanthology.org/2025.naacl-long.481/); [full paper, §4.2, Tables 1–3](https://aclanthology.org/2025.naacl-long.481.pdf).

- **Evidence/sample:** Five chess-knowledgeable raters each judge 250 comments: five methods on 50 moves. Concept-guided commentary improves several quality measures, but correctness remains imperfect; reported error categories include illegal moves/nonexistent pieces and faulty positional claims. Agreement varies by evaluation dimension.
- **Limit:** Commentary preference and correctness ratings are not retained learning or causal faithfulness to engine internals. An LLM-based judge cannot certify explanations independently by itself.
- **Project implication:** Audit legality, board facts, tactical claims, alternatives, and uncertainty separately from prose quality. Require each instructional claim to cite a saved position/continuation or be marked an editorial interpretation. Use blinded human adjudication before release.
- **Evidence class:** Human assessment of outputs; not human-learning evidence.

### 12. Stronger chess-language models do not remove the need for evidence

**Tang et al.** *Grounded Chess Reasoning in Language Models via Master Distillation.* Preprint v1, 20 March 2026. The model is **C1**; that is not the paper’s title. [Paper, §3–5](https://arxiv.org/html/2603.20510v1); [official code](https://github.com/CSSLab/C1).

- **Evidence/sample:** C1-4B reports 48.1% pass@1 on 900 tactical puzzles, using engine-conditioned explanation synthesis followed by supervised and reinforcement learning. The test includes theme and difficulty subsets.
- **Limit:** Correct final moves do not establish that every explanation statement is correct or faithfully reproduces the engine’s internal computation. The paper itself notes weaker/negative reinforcement-learning gains on expert puzzles and possible explanation-faithfulness problems. No human-learning experiment is reported.
- **Project implication:** An LLM may draft a concise explanation from verified evidence, but should not supply the answer key, invent an unseen refutation, or approve its own lesson. The existing private review desk is an appropriate gate.
- **Evidence class:** Model puzzle-solving benchmark, preprint.

## What to do with this evidence

These are project proposals, not results reported by the papers.

### A. A behavioral validity audit before another large mining run

History sensitivity has already been measured in [version 2](MINING_V2.md): Maia3-5M at fixed 2000 inputs changes its first choice on 322 of 2,000 positions (16.1%); mean total variation is 0.121685 in the [saved summary](../results/mining_v2_summary.json). The proposed extension is sensitivity of **acceptable-set classification and calibration**, then carefully targeted evaluation of the larger FEN-only editorial pool. It is not a first-ever history comparison for this project.

Define an engine-acceptable move set using the frozen policy and evaluate the **sum** of human-model probabilities assigned to it. Keep top-one matching, acceptable-set probability, and actual played-move quality as distinct columns. A position with several nearly equivalent moves should not be called difficult merely because one particular engine move has low probability.

Use untouched games for a final evaluation only after choices are frozen. Develop on editorial/development data. Preserve all-origin game exclusions, canonical-board separation, BOT checks, public-puzzle exposure, and missing-history flags. Include ordinary sampled positions and threshold-near controls; evaluating only retained items cannot measure recall, population calibration, or the full selection error rate.

Compare Maia-2 with real-history Maia-3, stratifying by source/time control instead of presenting a universal model ranking. Evaluate reliability, log loss, Brier score for the acceptable-set event, and actual-move loss where available. Cluster uncertainty by source game and consider repeat-player sensitivity. Agreeing model predictions are corroboration, not multiple independent human experiments. Future puzzle responses need their own calibration because finding a move after an explicit puzzle prompt differs from choosing it during a game.

**Deliverable:** A frozen diagnostic table showing which candidates are robust, model-dependent, context-sensitive, or unresolved. This can narrow future compute without overwriting prior results.

### B. A lesson must survive a competing-move test

For each candidate in the private 24-position review set, create a short evidence record:

1. The concrete decision and why the tempting alternative is tempting.
2. The move or acceptable set supported by saved searches.
3. The relevant opponent reply and the next player decision.
4. An explanation whose factual statements can be checked against the board and saved branches.
5. A related example from a different source game, plus a contrasting case where the proposed rule does not apply.

If saved branches do not establish a refutation, mark it unresolved. A legal principal variation illustrates one line, not an exhaustive proof. Do not generate board perturbations and assume they preserve the teaching concept; every new position requires chess and provenance validation. Do not expose formal validation/test origins while authoring.

**Deliverable:** A small number of defensible lesson families with recorded rejects and reasons, rather than 24 automatically approved “new concepts.”

### C. Separate “better hints” from “better grouping” in a study

The existing grouped-versus-shuffled learning protocol tests organization. Keep help policy, explanation length, feedback availability, and training time comparable between its arms. Changing all of those simultaneously would make the treatment uninterpretable.

A later hint-policy experiment can compare an initial unaided attempt followed by a limited cue with answer-first access. Record first choice, acceptable-move quality, hints used, time, the subsequent decision, and delayed answers on genuinely unseen related positions. A completion count, return visit, or repeat answer is a product measure, not the primary evidence for generalization.

**Deliverable:** A preregistered, feasible experiment with one primary transfer endpoint and transparent exploratory outcomes. Participant recruitment remains necessary for human-learning claims; more model analysis cannot replace it.

## Citation corrections and unresolved access

- The existing arXiv identifiers for Schut, Maia-2, Chessformer, Level Up, Jenner, Lin, and C1 resolve to the intended works; this audit did not find fabricated identifiers among those entries.
- Schut has a 2025 journal version with a slightly changed title, alongside its 2023 preprint. The bibliography now distinguishes them.
- “CSSLab / Chessformer / Maia-3,” “Level Up,” and “C1” were shorthand. Full paper titles, identifiable authors, and verified dates have been restored. CCC’s full NAACL title is now given.
- The two new Poulidis entries are working papers. Full methods and precise outcome definitions still need checking before adopting numerical effect-size claims or reproducing their intervention.
- The recent preprints are leads with concrete methods to inspect, not grounds for describing our trainer as proven, novel, calibrated, or causally interpretable.

## Three priorities

1. **Validate what “rare for humans” means on held-out data**, especially acceptable alternatives, genuine history, and time-control mismatch.
2. **Turn a few retained positions into evidence-backed contrasting lessons**, with continuation questions and explicit rejection reasons.
3. **Measure later unaided transfer**, using matched instruction conditions; keep human efficacy claims pending until those data exist.
