"""scripts/bootstrap.sh on a fresh checkout. .env.example leaves its secrets empty on purpose, and
compose refuses to start with them empty, so a plain copy would make a first run fail; an admin password
defaulting to `admin` would be one anyone knows. The first run fills every empty secret with a random
one, the admin's included, and says where it is; `--env-only` stops there."""
import re
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SECRETS = ("SUPERSET_SECRET_KEY", "SUPERSET_GUEST_TOKEN_SECRET", "SUPERSET_DB_PASSWORD",
           "DASHBOARD_REDIS_PASSWORD",
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


def test_the_standalone_texts_promise_only_what_the_stack_forwards():
    """docker-compose.aisc.yml and bootstrap.sh's "Next:" said the platform's
    bridge registers project connections on this stack, but the standalone environment forwards neither
    DASHBOARD_BRIDGE_TOKEN nor DASHBOARD_RO_PASSWORD, so every registration was a 401 (README lines 143-144
    said so). Each variable the overlay tells you to set is forwarded, and a text that promises the bridge
    has the bridge's variables forwarded."""
    import yaml

    env = yaml.safe_load((REPO / "docker-compose.yml").read_text())["x-superset-env"]
    overlay = (REPO / "docker-compose.aisc.yml").read_text()
    named = set(re.findall(r"^#\s+([A-Z_]+)=", overlay, re.M)) - {"AISC_NETWORK"}
    assert named and named <= set(env), named - set(env)
    bridge_ready = {"DASHBOARD_BRIDGE_TOKEN", "DASHBOARD_RO_PASSWORD"} <= set(env)
    for text in (overlay, (REPO / "scripts/bootstrap.sh").read_text()):
        flat = " ".join(line.lstrip("# ").strip() for line in text.splitlines())
        promises = re.search(r"bridge registers|registered by the platform's bridge", flat)
        assert bridge_ready or not promises, promises and promises.group(0)
