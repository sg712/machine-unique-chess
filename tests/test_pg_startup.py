"""Offline lock-order and cleanup regressions; never connect to a database."""
from concurrent.futures import ThreadPoolExecutor
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_app import site


class SimulatedDatabase:
    """Model the transaction advisory lock, not PostgreSQL's SQL implementation."""
    def __init__(self, hold_first=False, fail_ddl=False, fail_commit=False):
        self.lock = threading.Lock()
        self.guard = threading.Lock()
        self.connections = []
        self.events = []
        self.hold_first = hold_first
        self.fail_ddl = fail_ddl
        self.fail_commit = fail_commit
        self.first_ddl = threading.Event()
        self.release_first = threading.Event()
        self.second_lock_attempt = threading.Event()

    def connect(self, url):
        if url != "offline-fake-database":
            raise AssertionError("Tests must not use real connection information")
        with self.guard:
            connection = SimulatedConnection(self, len(self.connections))
            self.connections.append(connection)
            return connection


class SimulatedConnection:
    def __init__(self, database, number):
        self.database, self.number = database, number
        self.held = False
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        # Match psycopg3's transaction behavior, including commit errors that
        # interrupt its normal close path. init_db must still close in that case.
        if kind is not None:
            self.rollback()
        else:
            self.commit()
        self.close()

    def execute(self, sql, params=()):
        compact = " ".join(sql.split())
        if compact == "SELECT pg_advisory_xact_lock(%s)":
            if params != (site.PG_MIGRATION_LOCK,):
                raise AssertionError("Unexpected lock namespace")
            if self.number == 1:
                self.database.second_lock_attempt.set()
            if not self.database.lock.acquire(timeout=3):
                raise AssertionError("Startup lock was not released")
            self.held = True
            self.database.events.append((self.number, "lock", params[0]))
            return
        if not self.held:
            raise AssertionError("DDL ran before the startup transaction lock")
        if not compact.startswith(("CREATE ", "ALTER ")):
            raise AssertionError("Unexpected migration statement")
        self.database.events.append((self.number, "ddl", compact))
        if self.number == 0 and not self.database.first_ddl.is_set():
            self.database.first_ddl.set()
            if self.database.hold_first and not self.database.release_first.wait(timeout=3):
                raise AssertionError("Test did not release the first startup")
        if self.database.fail_ddl:
            raise RuntimeError("simulated DDL failure")

    def commit(self):
        self.database.events.append((self.number, "commit", None))
        if self.database.fail_commit:
            raise RuntimeError("simulated commit failure")
        self.release()

    def rollback(self):
        self.database.events.append((self.number, "rollback", None))
        self.release()

    def release(self):
        if self.held:
            self.held = False
            self.database.lock.release()

    def close(self):
        if not self.closed:
            self.database.events.append((self.number, "close", None))
            self.release()
            self.closed = True


class PostgresStartupTests(unittest.TestCase):
    def run_with(self, database, callback):
        with patch.object(site, "DATABASE_URL", "offline-fake-database"), \
             patch.object(site, "psycopg", SimpleNamespace(connect=database.connect), create=True):
            callback()

    def test_concurrent_cold_starts_serialize_every_ddl_until_commit(self):
        database = SimulatedDatabase(hold_first=True)

        def concurrent():
            with ThreadPoolExecutor(max_workers=2) as executor:
                first = executor.submit(site.init_db)
                try:
                    self.assertTrue(database.first_ddl.wait(timeout=2))
                    second = executor.submit(site.init_db)
                    self.assertTrue(database.second_lock_attempt.wait(timeout=2))
                    self.assertFalse(any(number == 1 and event == "ddl"
                                         for number, event, _ in database.events))
                finally:
                    database.release_first.set()
                first.result(timeout=4)
                second.result(timeout=4)

        self.run_with(database, concurrent)
        events = database.events
        first_commit = next(i for i, (number, event, _) in enumerate(events) if number == 0 and event == "commit")
        second_lock = next(i for i, (number, event, _) in enumerate(events) if number == 1 and event == "lock")
        self.assertGreater(second_lock, first_commit)
        expected_ddl = sum(bool(statement.strip()) for statement in site.PG_SCHEMA.split(";")) + 2
        for number, connection in enumerate(database.connections):
            own = [event for owner, event, _ in events if owner == number]
            self.assertEqual(own[0], "lock")
            self.assertEqual(own.count("ddl"), expected_ddl)
            self.assertEqual(own[-2:], ["commit", "close"])
            self.assertTrue(connection.closed)
        self.assertFalse(database.lock.locked())

    def test_ddl_failure_rolls_back_closes_and_releases_lock_for_next_startup(self):
        database = SimulatedDatabase(fail_ddl=True)

        def retry():
            with self.assertRaisesRegex(RuntimeError, "simulated DDL failure"):
                site.init_db()
            self.assertTrue(database.connections[0].closed)
            self.assertFalse(database.lock.locked())
            database.fail_ddl = False
            site.init_db()

        self.run_with(database, retry)
        self.assertIn((0, "rollback", None), database.events)
        self.assertNotIn((0, "commit", None), database.events)
        self.assertTrue(all(connection.closed for connection in database.connections))

    def test_commit_failure_still_closes_connection_and_releases_transaction_lock(self):
        database = SimulatedDatabase(fail_commit=True)
        def failing_startup():
            with self.assertRaisesRegex(RuntimeError, "simulated commit failure"):
                site.init_db()
        self.run_with(database, failing_startup)
        self.assertTrue(database.connections[0].closed)
        self.assertFalse(database.lock.locked())


if __name__ == "__main__":
    unittest.main()
