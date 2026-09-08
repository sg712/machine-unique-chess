# Engine verification and retry notes

The v2 scorer separates a short screening run from an exhaustive verification run. Screening values describe time-limited engine estimates and cannot certify a training answer. Deep verification requires every legal root move to be searched at depths 20 and 24, all requested depths to be achieved, no mate-valued scores, and an unchanged complete 20-centipawn acceptance set.

A UCI `lowerbound` or `upperbound` score is not a completed exact score, even when its reported depth reaches the target. The verification gate therefore also requires `score_is_exact` for every root. “Exact” here means the engine reported no UCI bound flag; it does not mean that finite-depth search proves perfect chess play.

Python-chess `analyse()` merges successive information dictionaries without deleting old keys. An earlier bound flag can survive a later exact score. The streaming search variant merges updates itself, removing old bound flags whenever a new score arrives. Tests cover both a final bound-only result, which fails verification, and a bound followed by an exact result, which clears the flag.

The scorer records its source SHA-256 alongside the engine binary, input, policy and settings hashes. A resumed output must match these settings. Preserve the old output and source snapshot when changing scoring logic. Older screens that did not capture bounds cannot retrospectively become verified material.

## Interpreting probability and regret bounds

A partially searched position may contain an unsearched move that is substantially better than every examined move. This changes the reference score even if the policy assigns that move zero probability. The tight original bounds are therefore retained as explicitly conditional fields:

- `conditional_p_good_lower`
- `conditional_capped_regret_upper_cp`
- `conditional_loss_upper` for WDL sensitivity

The global `p_good_lower` is zero and global capped-regret upper bound is 300 cp whenever any legal policy move is unsearched. The global WDL-loss upper bound is one until all moves have a WDL value. Coverage is checked by move identity, not only by the remaining probability mass. The good-move upper bound and regret lower bound remain conservative relative to the recorded root scores. These are bounds on the frozen numerical approximation; they do not encompass arbitrary deeper-search changes.

Stockfish WDL is its self-play expectation, not a human winning probability. Winning mate scores are retained as mates and suppress numerical centipawn summaries. Candidate selection for a finite-centipawn study should exclude mate rows; a screening row's numeric `best` field is not the overall best move when a different root has a winning mate.

## Efficient deeper retries

`scripts/mining_v2_deep_retry.py` reads a prior deep output and its manifest. It checks the engine/options, prior source-file hash and the current item's FEN, source game and full history against the prior inputs. It records the prior output hash, manifest hash and scorer version in the new run. Use a new output path when any setting changes.

For a previously stable acceptance set, the helper reuses only roots whose recorded target and achieved depths match the requirement, whose score is exact and whose principal variation is legal and starts with the requested root. Missing metadata, a bound flag, an early stop or a corrupt continuation triggers a fresh search for that root. **If the previous acceptance set was unstable, every root at both depths is searched again.** The final acceptance and verification gates are recomputed after combining reusable and fresh evidence. Reuse is recorded per root; it does not silently count old searches as new engine work.

Example after the streaming scorer is installed:

```sh
python scripts/mining_v2_deep_retry.py --input /path/shortlist.jsonl --policies /path/policies.jsonl --prior /path/first-deep.jsonl --output /path/retry-deep.jsonl --deep-seconds 30 --workers 4
```

Thirty seconds is a maximum per root, not a guarantee of reaching depth 24. Results that still fail any gate remain unverified. Legal stable moves and verified scores are necessary evidence for a study bank, but family quality, boundary-case meaning, independent chess review and participant consent remain separate requirements.
