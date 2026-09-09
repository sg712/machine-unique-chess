import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("full_pipeline", ROOT / "scripts/mining_v3_full_deep_pipeline.py")
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


class PipelineTests(unittest.TestCase):
    def test_battery_pause_waits_for_ac_then_resumes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            launches, sleeps, validations = [], [], []
            def launch(command):
                launches.append(command)
                pipeline.save(root / "run.json", {"complete": len(launches) == 2,
                              "pause_reason": "battery" if len(launches) == 1 else None})
                return 75 if len(launches) == 1 else 0
            power = iter([False, False, True])
            pipeline.drive_engine(["engine"], root, {}, root / "pipeline.json", {},
                                  launch=launch, power=lambda: next(power), sleep=sleeps.append,
                                  validate_code=lambda value: validations.append(value))
            self.assertEqual(len(launches), 2)
            self.assertEqual(sleeps, [30, 30])
            self.assertEqual(len(validations), 4)

    def test_unexpected_failure_is_not_retried(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def launch(command):
                pipeline.save(root / "run.json", {"complete": False, "error": "bad evidence"})
                return 1
            with self.assertRaisesRegex(RuntimeError, "bad evidence"):
                pipeline.drive_engine([], root, {}, root / "pipeline.json", {}, launch=launch,
                                      power=lambda: self.fail("must not wait"), validate_code=lambda _: None)

    def test_stale_battery_manifest_does_not_mask_new_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pipeline.save(root / "run.json", {"complete": False, "pause_reason": "battery"})
            with self.assertRaises(RuntimeError):
                pipeline.drive_engine([], root, {}, root / "pipeline.json", {}, launch=lambda _: 75,
                                      power=lambda: self.fail("must not retry"), validate_code=lambda _: None)

    def test_success_exit_requires_complete_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaisesRegex(RuntimeError, "completion evidence missing"):
                pipeline.drive_engine([], root, {}, root / "pipeline.json", {},
                                      launch=lambda _: 0, validate_code=lambda _: None)

    def test_code_change_aborts_before_search(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def changed(_):
                raise ValueError("code changed")
            with self.assertRaisesRegex(ValueError, "code changed"):
                pipeline.drive_engine([], root, {}, root / "pipeline.json", {},
                                      launch=lambda _: self.fail("must not launch"), validate_code=changed)

    def test_report_preserves_an_existing_different_document(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "report.md"
            target.write_text("User's own notes")
            result = pipeline.write_report({"counts": {"checked_n": 4345, "engine_verified_n": 123,
                                          "survives_candidate_criterion_n": 45}}, target)
            self.assertEqual(target.read_text(), "User's own notes")
            self.assertNotEqual(result, target)
            self.assertIn("4,345", result.read_text())
            self.assertIn("45", result.read_text())

    def test_interrupt_cleans_owned_engine_process_group(self):
        child = Mock(pid=24680)
        child.poll.return_value = None
        child.wait.side_effect = [KeyboardInterrupt(),
            pipeline.subprocess.TimeoutExpired("engine", 30),
            pipeline.subprocess.TimeoutExpired("engine", 10), 0]
        with patch.object(pipeline.subprocess, "Popen", return_value=child) as spawn, \
             patch.object(pipeline.os, "killpg") as killpg:
            with self.assertRaises(KeyboardInterrupt):
                pipeline.run_child(["engine"])
        self.assertTrue(spawn.call_args.kwargs["start_new_session"])
        child.send_signal.assert_called_once_with(pipeline.signal.SIGINT)
        self.assertIn(((24680, pipeline.signal.SIGTERM),), [tuple(call)[:1] for call in killpg.call_args_list])
        self.assertEqual(killpg.call_args.args, (24680, pipeline.signal.SIGKILL))

    def test_relative_run_path_is_resolved_before_child_changes_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            repository = root / "repository"
            (repository / "results").mkdir(parents=True)
            run_dir = root / "out"
            run_dir.mkdir()
            (run_dir / "run.json").write_text('{"complete":true}')
            final = {"complete": True, "counts": {"checked_n": 4345, "engine_verified_n": 1,
                     "survives_candidate_criterion_n": 1},
                     "fingerprints": {"run_manifest_snapshot_sha256": pipeline.digest(run_dir / "run.json")}}
            (run_dir / "validated_summary.json").write_text(json.dumps(final))
            old_cwd = Path.cwd()
            try:
                os.chdir(root)
                with patch.object(pipeline, "ROOT", repository), \
                     patch.object(pipeline.sys, "argv", ["pipeline", "--run-dir", "out", "--report", "report.md"]), \
                     patch.object(pipeline.signal, "signal"), \
                     patch.object(pipeline, "fingerprints", return_value={}), \
                     patch.object(pipeline, "check_frozen"), \
                     patch.object(pipeline, "drive_engine") as drive, \
                     patch.object(pipeline, "run_child", return_value=0):
                    pipeline.main()
                command, run_dir = drive.call_args.args[:2]
                self.assertEqual(run_dir, root / "out")
                self.assertEqual(command[-1], str(root / "out"))
                self.assertTrue(json.loads((root / "out/pipeline.json").read_text())["complete"])
            finally:
                os.chdir(old_cwd)

    def test_summary_cannot_publish_results_from_another_run(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "run.json").write_text('{"complete":true}')
            (root / "summary.json").write_text(json.dumps({"complete": True,
                "fingerprints": {"run_manifest_snapshot_sha256": "not-this-run"}}))
            with self.assertRaisesRegex(ValueError, "this completed run"):
                pipeline.publish_summary(root / "summary.json", root, root / "public.json")
            self.assertFalse((root / "public.json").exists())


if __name__ == "__main__":
    unittest.main()
