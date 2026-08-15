# Study platform

Real multi-participant version of the transfer experiment.

```bash
conda activate unnamed-concepts
python webapp/app.py            # http://127.0.0.1:5055
```

- **Accounts**: six-character resumable codes, no email or password (standard for
  research participation, and nothing to leak).
- **Protocol**: baseline (8 public positions) → study (prototype lines, no commentary)
  → retest (10 unseen). Each phase gated on the previous; every answer written to
  `study.db` as it happens, so a closed tab loses nothing.
- **Board**: `static/board.js` — pieces are real elements that slide between squares.
  Legality comes from the server (python-chess), so no client-side chess engine.
- **Aggregate**: `/results` and `/` show cross-participant rates and the paired
  baseline→retest delta once anyone completes both.

Deployment: any host that runs Flask (Render, Fly, Railway). Set a real
`app.secret_key` and move `study.db` to a persistent volume first.
