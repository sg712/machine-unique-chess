"""White expansion invariants, including resume and genuine history."""
from collections import Counter
import base64
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import random

import chess
import chess.pgn

from scripts.mining_v2_sampling import canonical_fen, validate_rows
from scripts.mining_v3_sampling import (Selector, cached_zstd_chunks, cell, game_blocks, reconcile_profile,
                                        validate_selection, white_candidates)
from tests.test_sampling_v2 import PGN, source


class WhiteExpansionTests(unittest.TestCase):
    def rows(self):
        rows, reason = white_candidates(chess.pgn.read_game(io.StringIO(PGN)), source())
        self.assertIsNone(reason)
        return rows

    def test_real_white_turns_replay_and_clock_missingness(self):
        rows = self.rows()
        self.assertEqual([r["ply"] for r in rows], [15, 19, 23, 27, 31, 35, 39])
        self.assertTrue(all(chess.Board(r["fen"]).turn for r in rows))
        self.assertTrue(validate_rows(rows)["history_replay_valid"])
        self.assertTrue(all(r["mover_elo"] == 2000 for r in rows))
        self.assertTrue(all(r["clock_seconds_before"] is None for r in rows))

    def test_additional_real_plies_preserve_history_and_per_game_cap(self):
        game = chess.pgn.read_game(io.StringIO(PGN))
        rows, reason = white_candidates(game, source(), sampled_plies=range(1, 41))
        self.assertIsNone(reason)
        self.assertEqual(len(rows), 20)
        self.assertTrue(validate_rows(rows)["history_replay_valid"])
        with tempfile.TemporaryDirectory() as directory:
            output, pilot = Path(directory) / "out.jsonl", Path(directory) / "pilot.jsonl"
            pilot.write_text("")
            selector = Selector(Counter(cell(r) for r in rows), output, pilot)
            with output.open("a") as f:
                self.assertEqual(selector.add(rows, f), 15)
                self.assertEqual(selector.add(rows, f), 0)
            self.assertEqual(max(selector.games.values()), 15)

    def test_public_position_after_window_and_bot_exclusion(self):
        game = chess.pgn.read_game(io.StringIO(PGN))
        last = canonical_fen(list(game.mainline())[-1].board().fen())
        self.assertEqual(white_candidates(game, source(), excluded_fens={last})[1], "public_position_in_game")
        game.headers["WhiteTitle"] = "BOT"
        self.assertEqual(white_candidates(game, source())[1], "bot")

    def test_resume_quotas_and_pilot_duplicates(self):
        rows = self.rows()
        targets = Counter(cell(r) for r in rows)
        with tempfile.TemporaryDirectory() as directory:
            output, pilot = Path(directory) / "out.jsonl", Path(directory) / "pilot.jsonl"
            pilot.write_text(json.dumps(rows[0]) + "\n")
            selector = Selector(targets, output, pilot)
            with output.open("a") as f:
                self.assertEqual(selector.add(rows, f), len(rows) - 1)
            resumed = Selector(targets, output, pilot)
            with output.open("a") as f:
                self.assertEqual(resumed.add(rows, f), 0)
            self.assertEqual(resumed.counts, selector.counts)
            self.assertEqual(len(output.read_text().splitlines()), len(rows) - 1)
            self.assertTrue(all(json.loads(line)["shares_game_with_pilot"] for line in output.read_text().splitlines()))

    def test_bounded_stream_never_parses_incomplete_tail(self):
        blocks = list(game_blocks([PGN[:30], PGN[30:] + "\n", "\n[Event \"partial\"]\n"]))
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].rstrip("\n"), PGN.rstrip("\n"))

    def test_corrected_profile_reselection_preserves_evidence(self):
        rows = self.rows()
        targets = Counter(cell(r) for r in rows[1:])
        with tempfile.TemporaryDirectory() as directory:
            output, pilot = Path(directory) / "out.jsonl", Path(directory) / "pilot.jsonl"
            original = "".join(json.dumps(r) + "\n" for r in rows)
            output.write_text(original)
            pilot.write_text("")
            report = reconcile_profile(output, targets)
            self.assertEqual(report["removed"], 1)
            self.assertEqual((output.parent / report["previous_positions_archive"]).read_text(), original)
            verified = validate_selection(output, targets, pilot)
            self.assertEqual(verified["positions"], len(rows) - 1)
            self.assertTrue(verified["exact_target_cells"])
            with self.assertRaisesRegex(ValueError, "quotas"):
                validate_selection(output, Counter(cell(r) for r in rows), pilot)

    def test_network_drop_resumes_exact_compressed_byte_without_duplicate_text(self):
        import pyzstd
        payload = base64.b64encode(random.Random(19).randbytes(1_500_000)).decode("ascii")
        compressed = pyzstd.compress(payload.encode())
        self.assertGreater(len(compressed), 1 << 20)
        requests = []

        class Response:
            def __init__(self, start):
                self.position, self.start, self.calls = start, start, 0
                self.status = 206 if start else 200
                self.headers = {"ETag": '"unchanged-archive"'}
                if start:
                    self.headers["Content-Range"] = f"bytes {start}-{len(compressed)-1}/{len(compressed)}"

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, count):
                self.calls += 1
                if self.start == 0 and self.calls == 2:
                    raise TimeoutError("synthetic connection loss")
                data = compressed[self.position:self.position + count]
                self.position += len(data)
                return data

        def open_response(req, **kwargs):
            requests.append(req)
            header = req.get_header("Range")
            return Response(int(header[6:-1]) if header else 0)

        with tempfile.TemporaryDirectory() as directory, patch("urllib.request.urlopen", side_effect=open_response):
            cache = Path(directory) / "prefix.zst"
            stats = {}
            reconstructed = "".join(cached_zstd_chunks("https://example.test/archive.zst", cache, 3, stats))
            self.assertEqual(reconstructed, payload)
            self.assertEqual(cache.read_bytes(), compressed)
            self.assertEqual(len(stats["network_retries"]), 1)
            self.assertEqual(requests[1].get_header("Range"), f"bytes={1 << 20}-")
            self.assertEqual(requests[1].get_header("If-range"), '"unchanged-archive"')


if __name__ == "__main__":
    unittest.main()
