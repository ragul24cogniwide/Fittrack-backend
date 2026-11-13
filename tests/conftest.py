import os
import tempfile

# Tests must never touch the real NeonDB: point the app at a throwaway SQLite
# file before any app module (and its engine) is imported.
# Set TEST_DATABASE_URL to run against a disposable Postgres database instead.
_db_dir = tempfile.mkdtemp(prefix="fittrack-tests-")
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", f"sqlite+aiosqlite:///{_db_dir}/test.db"
)
os.environ["ENVIRONMENT"] = "test"
os.environ["DEBUG"] = "false"
os.environ.pop("RENDER", None)
os.environ["GOOGLE_CLIENT_ID"] = ""
os.environ["GOOGLE_CLIENT_SECRET"] = ""
