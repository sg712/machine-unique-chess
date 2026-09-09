"""Run the finite candidate census, resume battery pauses, then validate results.

This owns one local computation. It does not install a scheduler or publish a
deployment. Search evidence and scoring dependencies remain frozen throughout.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
CODE_FILES = (
    "mining_v3_full_deep_pipeline.py", "mining_v3_full_deep.py",
    "mining_v3_full_deep_selection.py", "mining_v3_full_deep_summary.py",
    "mining_v3_deep.py", "mining_v3_deep_selection.py", "mining_v3_deep_summary.py",
    "mining_v2_engine.py", "mining_v2_sampling.py", "mining_v2_summary.py",
    "mining_v3_dataset.py", "mining_v3_io.py",
)


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def save(path, data):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as stream:
        json.dump(data, stream, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def ac_power_connected():
    try:
        value = subprocess.run(["pmset", "-g", "batt"], capture_output=True,
                               text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return value.returncode == 0 and "'AC Power'" in value.stdout


def fingerprints(root=ROOT):
    return {name: digest(root / "scripts" / name) for name in CODE_FILES}


def check_frozen(expected, root=ROOT):
    if fingerprints(root) != expected:
        raise ValueError("Pipeline or scoring/reporting code changed; review before resuming")


def run_child(command):
    child = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, start_new_session=True)
    def stop_group(signum):
        try:
            os.killpg(child.pid, signum)
        except ProcessLookupError:
            pass
    try:
        return child.wait()
    except BaseException:
        try:
            if child.poll() is None:
                child.send_signal(signal.SIGINT)
                try:
                    child.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    stop_group(signal.SIGTERM)
                    try:
                        child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        stop_group(signal.SIGKILL)
                        child.wait(timeout=10)
        finally:
            # The owned session may still contain orphaned engine grandchildren.
            stop_group(signal.SIGKILL)
        raise


def drive_engine(command, run_dir, state, state_path, frozen,
                 launch=run_child, power=ac_power_connected, sleep=time.sleep,
                 validate_code=check_frozen):
    while True:
        validate_code(frozen)
        state.update(stage="searching", updated_at=time.time())
        save(state_path, state)
        run_path = run_dir / "run.json"
        previous_run_hash = digest(run_path) if run_path.exists() else None
        code = launch(command)
        run = json.loads(run_path.read_text()) if run_path.exists() else {}
        if code == 0 and run.get("complete") is True:
            return
        if (code != 75 or run.get("pause_reason") != "battery" or
                (previous_run_hash is not None and digest(run_path) == previous_run_hash)):
            raise RuntimeError(f"Engine run stopped (exit {code}): {run.get('error', 'completion evidence missing')}")
        state.update(stage="waiting_for_ac_power", updated_at=time.time())
        save(state_path, state)
        print("Battery pause saved; this job will resume when AC power is connected.", flush=True)
        while not power():
            sleep(30)
            validate_code(frozen)
        print("AC power connected; resuming the same frozen search.", flush=True)


def write_report(summary, output):
    """A local completion note; final counts are read from validated aggregates."""
    output.parent.mkdir(parents=True, exist_ok=True)
    counts = summary["counts"]
    checked = counts["checked_n"]
    stable = counts["engine_verified_n"]
    retained = counts["survives_candidate_criterion_n"]
    text = (
        "# Full candidate depth checks\n\n"
        f"Completed {datetime.now(timezone.utc).date().isoformat()} UTC.\n\n"
        f"All **{checked:,} distinct first-pass candidates** have completed every legal-move "
        "check at depths 20 and 24. The original 200 checks were reused only after validation.\n\n"
        f"**{stable:,} met the engine-stability rule; {retained:,} also retained the full "
        "candidate criterion.** These are engine and model results. Explanations and chess "
        "review remain necessary before adding positions to the trainer.\n\n"
        "The full census includes BOT-tagged and previously public games as well as games "
        "without BOT tags. Their results are reported separately in the aggregate. Several "
        "positions can come from the same game; the position count is not a count of "
        "independent human observations.\n\n"
        "The completed results and all detailed source-group counts are saved in "
        f"[the validated aggregate]({ROOT / 'results/mining_v3_full_deep.json'}). "
        "Raw positions, solutions and source-game identities remain private.\n\n"
        "Elapsed clock time may include computer sleep; search durations overlap across "
        "workers and are not CPU-time measurements. See the recorded timing definitions "
        "before estimating further compute costs.\n"
    )
    if output.exists() and output.read_text() != text:
        output = output.with_name(output.stem + " - " + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + output.suffix)
        if output.exists():
            raise FileExistsError("Completion report destination already exists")
    temporary = output.with_suffix(".tmp")
    temporary.write_text(text)
    temporary.replace(output)
    return output


def publish_summary(summary_path, run_dir, public_output):
    summary = json.loads(summary_path.read_text())
    if (summary.get("complete") is not True or
            summary.get("fingerprints", {}).get("run_manifest_snapshot_sha256") != digest(run_dir / "run.json")):
        raise ValueError("Final aggregate does not identify this completed run")
    lock_path = ROOT / "results/mining_v3/full_deep_publication.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        save(public_output, summary)
        published_hash = digest(public_output)
    return summary, published_hash


def main():
    def terminate(signum, frame):
        raise KeyboardInterrupt("Termination requested")
    signal.signal(signal.SIGTERM, terminate)
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--run-dir", type=Path, default=ROOT / "results/mining_v3/deep_all")
    ap.add_argument("--report", type=Path, default=Path.home() / "Documents/Machine Unique Chess/Full candidate depth checks - 2026-09-09.md")
    args = ap.parse_args()
    args.run_dir = args.run_dir.expanduser().resolve()
    args.report = args.report.expanduser().resolve()
    if args.workers < 1:
        ap.error("--workers must be positive")
    args.run_dir.mkdir(parents=True, exist_ok=True)
    state_path = args.run_dir / "pipeline.json"
    with (args.run_dir / "pipeline.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            ap.error("This finite pipeline already has an active owner")
        frozen = fingerprints()
        old = json.loads(state_path.read_text()) if state_path.exists() else None
        if old and old["code_sha256"] != frozen:
            raise ValueError("Frozen pipeline code changed; use a reviewed recovery procedure")
        public_output = ROOT / "results/mining_v3_full_deep.json"
        if old and old.get("complete"):
            if digest(public_output) != old.get("summary_sha256"):
                raise ValueError("Completed public result changed")
            print("Full candidate census already complete and validated.", flush=True)
            return
        state = {"schema_version": 1, "pid": os.getpid(), "complete": False,
                 "started_at": old["started_at"] if old else time.time(),
                 "code_sha256": frozen, "workers": args.workers, "stage": "starting"}
        save(state_path, state)
        try:
            drive_engine([sys.executable, "-u", str(ROOT / "scripts/mining_v3_full_deep.py"),
                          "--workers", str(args.workers), "--run-dir", str(args.run_dir)],
                         args.run_dir, state, state_path, frozen)
            check_frozen(frozen)
            state.update(stage="validating_complete_census", updated_at=time.time())
            save(state_path, state)
            validated_output = args.run_dir / "validated_summary.json"
            code = run_child([sys.executable, "-u", str(ROOT / "scripts/mining_v3_full_deep_summary.py"),
                              "--run-dir", str(args.run_dir), "--require-complete", "--output", str(validated_output)])
            if code != 0:
                raise RuntimeError(f"Final aggregate validation failed (exit {code})")
            check_frozen(frozen)
            summary, published_hash = publish_summary(validated_output, args.run_dir, public_output)
            report_path = write_report(summary, args.report)
            state.update(complete=True, stage="complete", finished_at=time.time(),
                         summary_sha256=published_hash, report_path=str(report_path),
                         report_sha256=digest(report_path))
            print("Full candidate census completed; validated aggregate and report saved.", flush=True)
        except BaseException as exc:
            state.update(stage="stopped_for_review", error=f"{type(exc).__name__}: {exc}",
                         finished_at=time.time())
            raise
        finally:
            state["updated_at"] = time.time()
            save(state_path, state)


if __name__ == "__main__":
    main()
