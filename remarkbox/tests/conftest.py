"""
Pytest configuration for parallel test execution.

This module configures pytest-xdist to use isolated databases per worker
to avoid SQLite locking issues during parallel test runs.
"""
import os
import pytest


def pytest_configure(config):
    """
    Configure test database isolation for parallel execution.

    Each pytest-xdist worker gets its own database file to prevent
    SQLite locking conflicts. WAL mode is enabled for better concurrency.
    """
    # Get worker ID (e.g., "gw0", "gw1", etc.) for pytest-xdist
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "master")

    # Set unique database path for this worker
    test_db_path = f"test-remarkbox_{worker_id}.sqlite"
    os.environ["TEST_DATABASE_PATH"] = test_db_path

    # Store for cleanup
    config.test_db_path = test_db_path


def pytest_unconfigure(config):
    """Clean up test database after all tests complete."""
    if hasattr(config, "test_db_path"):
        db_path = config.test_db_path
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception as e:
                print(f"Warning: Could not remove test database {db_path}: {e}")


@pytest.fixture(scope="session")
def db_engine(request):
    """
    Create a SQLAlchemy engine with WAL mode enabled for concurrency.

    WAL (Write-Ahead Logging) mode allows multiple readers while a writer
    is active, improving parallel test performance.
    """
    from sqlalchemy import create_engine, event

    # Use worker-specific database
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "master")
    db_path = f"test-remarkbox_{worker_id}.sqlite"
    db_url = f"sqlite:///{db_path}"

    engine = create_engine(
        db_url,
        echo=False,
        # Important: Use NullPool to avoid connection sharing issues
        poolclass=__import__("sqlalchemy.pool", fromlist=["NullPool"]).NullPool,
    )

    # Enable WAL mode for better concurrency
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        # Enable WAL mode for concurrent access
        cursor.execute("PRAGMA journal_mode=WAL")
        # Increase cache size for better performance
        cursor.execute("PRAGMA cache_size=-64000")  # 64MB
        # Enable foreign keys
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    yield engine

    # Cleanup
    engine.dispose()
