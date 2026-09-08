import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import chess
import chess.pgn

from scripts.mining_v3_recover import extend_cache, make_row, recovered_snapshot, scan_archives, time_class, write_corpus


PGN = '''[Event "Rated Rapid game"]
[Site "https://lichess.org/abcdefgh"]
[Date "2026.06.01"]
[White "A"]
[Black "B"]
[WhiteElo "2000"]
[BlackElo "2100"]
[TimeControl "600+5"]
[Result "*"]

1. e4 {[%clk 0:10:04]} e5 {[%clk 0:10:03]} 2. Nf3 Nc6 3. Bb5 a6 *
'''


def historical_rows(gid="abcdefgh"):
    game = chess.pgn.read_game(io.StringIO(PGN))
    board = game.board()
    rows = []
    for ply, move in enumerate(game.mainline_moves(), 1):
        if ply in (2, 4):
            rows.append(dict(fen=board.fen(), ply=str(ply), game_id=gid,
                             white_elo="2000", black_elo="2100", played_move=move.uci(),
                             source="club", batch="historical_fixture", engine_best=move.uci(),
                             best_cp="10", engine_margin="30", p_max="0.01", machine_unique="True"))
        board.push(move)
    return rows


class RecoveryTests(unittest.TestCase):
    def test_exact_recovery_retains_actual_history_and_clocks(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)
            (p / "games.pgn").write_text(PGN)
            rows = historical_rows()
            cache = scan_archives(rows, [p / "games.pgn"], p / "cache.json")
            result = make_row(rows[1], 1, cache, cache["master_sha256"])
            self.assertEqual(result["game_id"], "abcdefgh")
            self.assertEqual(result["history_uci"], ["e2e4", "e7e5", "g1f3"])
            self.assertEqual(result["history_fens"][-1], rows[1]["fen"])
            self.assertEqual(result["clock_seconds_before"], 603)
            self.assertIsNone(result["opponent_clock_seconds"])
            self.assertFalse(result["contains_bot"])

    def test_one_matching_position_does_not_recover_inconsistent_game(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)
            (p / "games.pgn").write_text(PGN)
            rows = historical_rows()
            rows[1]["played_move"] = "g8f6"
            cache = scan_archives(rows, [p / "games.pgn"], p / "cache.json")
            self.assertEqual(cache["hits"], {})
            result = make_row(rows[0], 0, cache, cache["master_sha256"])
            self.assertFalse(result["history_available"])
            self.assertEqual(result["history_uci"], [])
            self.assertIsNone(result["contains_bot"])
            self.assertIsNone(result["time_control"])

    def test_ambiguous_elite_source_is_not_guessed(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)
            (p / "games.pgn").write_text(PGN + "\n" + PGN.replace("abcdefgh", "ijklmnop"))
            rows = historical_rows("e1")
            for row in rows:
                row["source"] = "elite"
            cache = scan_archives(rows, [p / "games.pgn"], p / "cache.json")
            result = make_row(rows[0], 0, cache, cache["master_sha256"])
            self.assertEqual(result["source_match_count"], 2)
            self.assertEqual(result["history_recovery"], "ambiguous")
            self.assertFalse(result["history_available"])

    def test_clocks_are_not_carried_across_missing_annotation(self):
        game = {"initial_fen": chess.STARTING_FEN,
                "moves": ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6"],
                "clocks": [604, 603, None, None, None, None]}
        snap = recovered_snapshot(game, 6)
        self.assertIsNone(snap["clock_seconds_before"])
        self.assertIsNone(snap["opponent_clock_seconds"])

    def test_row_counts_and_canonical_duplicate_identity_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)
            rows = historical_rows()
            rows.append({**rows[0], "game_id": "another"})
            with (p / "master.csv").open("w") as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            (p / "pilot.jsonl").write_text("")
            from scripts.mining_v2_sampling import file_sha256
            cache = {"master_sha256": file_sha256(p / "master.csv"), "archives": [], "hits": {}, "games": {}}
            manifest = write_corpus(rows, [], cache, p / "black.jsonl", p / "manifest.json", p / "master.csv", p / "pilot.jsonl")
            saved = [json.loads(line) for line in (p / "black.jsonl").read_text().splitlines()]
            self.assertEqual(manifest["counts"]["positions"], 3)
            self.assertEqual(len({row["id"] for row in saved}), 3)
            self.assertEqual(saved[2]["canonical_duplicate_of"], saved[0]["id"])
            self.assertEqual(manifest["counts"]["canonical_duplicate_rows"], 1)

    def test_time_classes_and_missing_control(self):
        self.assertEqual(time_class("60+0"), "bullet")
        self.assertEqual(time_class("180+2"), "blitz")
        self.assertEqual(time_class("600+5"), "rapid")
        self.assertEqual(time_class("1800+0"), "classical")
        self.assertEqual(time_class(None), "unknown")
        for value in ("NaN+0", "600+inf", "-10+5", "600+-1", 600, {}, "bad"):
            self.assertEqual(time_class(value), "unknown")

    def test_documented_november_alias_repairs_rating_join(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)
            with zipfile.ZipFile(p / "elite_2025-11.zip", "w") as z:
                z.writestr("games.pgn", PGN.replace('[Black "B"]', '[Black "B"]\n[BlackTitle "BOT"]'))
            rows = historical_rows("e1")
            for row in rows:
                row["source"] = "elite"
                row["white_elo"] = "2500"
            cache = scan_archives(rows, [p / "elite_2025-11.zip"], p / "cache.json")
            result = make_row(rows[0], 0, cache, cache["master_sha256"])
            self.assertTrue(result["history_available"])
            self.assertTrue(result["ratings_corrected_from_source"])
            self.assertEqual(result["white_elo"], 2000)
            self.assertEqual(result["historical"]["white_elo"], 2500)
            self.assertTrue(result["mover_is_bot"])
            self.assertFalse(result["opponent_is_bot"])

    def test_extending_cache_preserves_ambiguity_and_rejects_wrong_corpus(self):
        old = {"master_sha256": "a", "archives": [], "games": {"old": {"clocks": []}}, "hits": {"0": ["old"]}}
        extra = {"master_sha256": "a", "archives": [], "games": {"new": {"clocks": []}}, "hits": {"0": ["new"]}}
        merged = extend_cache(old, extra)
        self.assertEqual(merged["hits"]["0"], ["new", "old"])
        with self.assertRaises(ValueError):
            extend_cache(old, {**extra, "master_sha256": "b"})

    def test_exact_club_url_repairs_rating_join_without_changing_position(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)
            (p / "games.pgn").write_text(PGN)
            rows = historical_rows()
            rows[0]["black_elo"] = "2300"
            cache = scan_archives(rows, [p / "games.pgn"], p / "cache.json")
            result = make_row(rows[0], 0, cache, cache["master_sha256"])
            self.assertTrue(result["history_available"])
            self.assertTrue(result["ratings_corrected_from_source"])
            self.assertEqual(result["black_elo"], 2100)
            self.assertEqual(result["historical"]["black_elo"], 2300)
            self.assertEqual(result["fen"], rows[0]["fen"])
            self.assertEqual(result["played_move"], rows[0]["played_move"])


if __name__ == "__main__":
    unittest.main()
