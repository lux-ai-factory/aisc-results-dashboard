"""Nothing here may run on a secret that is written in this repository.

A default secret means an install that does not set the variable runs on a
value anyone can read. `SUPERSET_SECRET_KEY` signs this dashboard's session
cookies, so whoever holds it can forge a session as any user, Admin included.

So the config refuses to start without it, and the compose file has no
fallback for it, for the metadata database's password, or for immudb's.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

#: A variable whose NAME says it holds a secret. `${MISTRAL_API_KEY:-}` is the
#: right shape and must stay allowed: no key, and no pretending there is one.
SECRETISH = re.compile(
    r"\$\{[A-Za-z_]*(PASSWORD|PASSWD|SECRET|TOKEN|API_?KEY|_KEY|CREDENTIALS?)[A-Za-z_]*:-[^}\s]"
)


def compose_files():
    return sorted(REPO.glob("docker-compose*.yml"))


def test_there_are_compose_files_to_check():
    assert compose_files(), "no compose file found; this test would pass vacuously"


@pytest.mark.parametrize("path", compose_files(), ids=lambda p: p.name)
def test_no_compose_file_falls_back_to_a_secret(path):
    offenders = [
        f"{path.name}:{n}: {line.strip()[:80]}"
        for n, line in enumerate(path.read_text().splitlines(), 1)
        if SECRETISH.search(line)
    ]
    assert not offenders, "shipped defaults:\n  " + "\n  ".join(offenders)


def test_the_config_has_no_fallback_secret_key():
    """A default in the config (`os.environ.get("SUPERSET_SECRET_KEY", "…")`)
    would defeat the compose file's refusal."""
    source = (REPO / "superset_config.py").read_text()
    assert 'os.environ.get("SUPERSET_SECRET_KEY"' not in source or \
        'os.environ["SUPERSET_SECRET_KEY"]' in source, \
        "the config still has a default for the secret key"
    assert "aisc-dev-secret-change-me" not in source, "the shipped key is still in the config"


def test_the_example_env_tells_you_to_generate_one():
    example = (REPO / ".env.example").read_text()
    assert "openssl rand" in example, ".env.example should say how to make a real one"
