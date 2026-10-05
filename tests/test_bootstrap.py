"""scripts/bootstrap.sh on a fresh checkout (code review 2026-10-05): it copied .env.example, whose
secrets are empty on purpose, and compose then refused to start, so a first run always failed; and the
admin's password defaulted to `admin`, printed at the end. The first run now fills every empty secret
with a random one, the admin's included, and says where it is; `--env-only` stops there."""
import re
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SECRETS = ("SUPERSET_SECRET_KEY", "SUPERSET_GUEST_TOKEN_SECRET", "SUPERSET_DB_PASSWORD", "IMMUDB_PASSWORD",
           "ADMIN_PASSWORD")


def _checkout(tmp_path):
    (tmp_path / "scripts").mkdir()
    shutil.copy(REPO / "scripts/bootstrap.sh", tmp_path / "scripts/bootstrap.sh")
    shutil.copy(REPO / ".env.example", tmp_path / ".env.example")
    return tmp_path


def _env(path):
    return dict(line.split("=", 1) for line in path.read_text().splitlines() if re.match(r"^[A-Z_]+=", line))


def test_a_first_run_fills_every_secret_with_a_random_one(tmp_path):
    root = _checkout(tmp_path)
    run = subprocess.run(["bash", "scripts/bootstrap.sh", "--env-only"], cwd=root, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    env = _env(root / ".env")
    for name in SECRETS:
        assert re.fullmatch(r"[0-9a-f]{32,}", env.get(name, "")), name
        assert env[name] not in run.stdout + run.stderr, f"{name} was printed"
    assert len({env[n] for n in SECRETS}) == len(SECRETS)


def test_a_second_run_keeps_what_is_there(tmp_path):
    root = _checkout(tmp_path)
    subprocess.run(["bash", "scripts/bootstrap.sh", "--env-only"], cwd=root, check=True, capture_output=True)
    first = _env(root / ".env")
    subprocess.run(["bash", "scripts/bootstrap.sh", "--env-only"], cwd=root, check=True, capture_output=True)
    assert _env(root / ".env") == first


def test_the_script_has_no_admin_password_of_its_own():
    text = (REPO / "scripts/bootstrap.sh").read_text()
    assert ":-admin}" not in text.replace('ADMIN_USER="${ADMIN_USER:-admin}"', "")
