import os
import tempfile

# Must be set before app.db is imported, so importing app.main never creates ./data.db.
os.environ.setdefault("TIMETRACK_DB", os.path.join(tempfile.mkdtemp(), "import-default.db"))

import pytest
from fastapi.testclient import TestClient

from app.db import get_connection, init_db
from app.main import create_app


@pytest.fixture
def conn():
    connection = get_connection(":memory:")
    init_db(connection)
    yield connection
    connection.close()


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def client(db_path):
    return TestClient(create_app(db_path))