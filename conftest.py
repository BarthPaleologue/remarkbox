"""
Pytest configuration for parallel test execution.

Lives at repo root, NOT in remarkbox/tests/: a nested conftest only loads
in processes that collect its directory. Under pytest-xdist the master
process skips collection unless given explicit path arguments, so hooks in
a nested conftest silently never fire there. Root conftests load everywhere.
"""
import glob
import os


def pytest_configure(config):
    """
    Configure test database isolation for parallel execution.

    Each pytest-xdist worker gets its own database file to prevent
    SQLite locking issues during parallel test runs.
    """
    # Get worker ID (e.g., "gw0", "gw1", etc.) for pytest-xdist
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "master")

    # Set unique database path for this worker
    os.environ["TEST_DATABASE_PATH"] = f"test-remarkbox_{worker_id}.sqlite"

    # Purge databases a killed or interrupted prior run left behind (master
    # only, before workers spawn). Stale rows masquerade as test failures.
    if worker_id == "master":
        _remove_test_databases()

    # Tests needing a live third-party endpoint. `make test` deselects these
    # so a deploy never hinges on someone else's uptime; `make test-integration`
    # runs them on purpose.
    config.addinivalue_line(
        "markers",
        "integration: requires a reachable external service (deselected by "
        "`make test`, run via `make test-integration`)",
    )


def pytest_runtest_setup(item):
    """
    Point TEST_DATABASE_PATH at a per-worker, per-module database file.

    Test modules build their own app via test.ini, whose sqlalchemy.url
    expands ${TEST_DATABASE_PATH} inside remarkbox.main(). Modules sharing
    one worker database couple them through mutable global state: any
    tearDownClass calling Base.metadata.drop_all() yanks tables out from
    under every other module bound to the same file. Re-pointing the env
    var before each test means each module's setUpClass/setUpModule binds
    its own file, so drops cannot cross module boundaries. Engines already
    created keep the path they were born with.
    """
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "master")
    module = getattr(item, "module", None)
    module_name = module.__name__.rsplit(".", 1)[-1] if module else "misc"
    os.environ["TEST_DATABASE_PATH"] = (
        f"test-remarkbox_{worker_id}_{module_name}.sqlite"
    )

    # Abort any transaction a previous test left on the process-global
    # thread-local transaction.manager. Test modules all join their sessions
    # to that one manager; a transaction spanning module boundaries makes a
    # commit two-phase-vote over another module's dead session, raising
    # ResourceClosedError and cascading. Every test starts on a fresh
    # transaction so only sessions it actually uses join in.
    import transaction

    try:
        transaction.abort()
    except Exception:
        pass


def pytest_unconfigure(config):
    """Clean up test databases after all tests complete (master only)."""
    if os.environ.get("PYTEST_XDIST_WORKER"):
        return
    _remove_test_databases()


def _remove_test_databases():
    for db_path in glob.glob("test-remarkbox_*.sqlite*"):
        try:
            os.remove(db_path)
        except OSError as e:
            print(f"Warning: Could not remove test database {db_path}: {e}")
