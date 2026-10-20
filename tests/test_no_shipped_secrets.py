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


def test_the_example_env_sets_each_variable_once_and_no_immudb_password():
    """A variable set twice in .env.example takes its later line, so a copied .env could run on a
    default (an empty password above, `immudb` below) without anyone seeing it."""
    names = [line.split("=", 1)[0] for line in (REPO / ".env.example").read_text().splitlines()
             if re.match(r"^[A-Z_][A-Z0-9_]*=", line)]
    assert sorted({n for n in names if names.count(n) > 1}) == []
    # The dashboard has no immudb of its own any more, so no IMMUDB_* at all
    assert not [n for n in names if n.startswith("IMMUDB_")], [n for n in names if n.startswith("IMMUDB_")]


CONFIG = (REPO / "superset_config.py").read_text()


def test_the_config_has_no_fallback_oidc_client_secret():
    """OIDC_CLIENT_SECRET has no fallback such as `superset-secret`: with AISC_OAUTH=1 and no secret
    set, the dashboard would run its Keycloak login on a value anyone could read."""
    assert "superset-secret" not in CONFIG
    assert 'os.environ["OIDC_CLIENT_SECRET"]' in CONFIG


def test_guest_tokens_are_signed_with_a_secret_of_this_install():
    """EMBEDDED_SUPERSET is on, so GUEST_TOKEN_JWT_SECRET must be set: unset, Superset's published
    default signs guest tokens."""
    assert 'GUEST_TOKEN_JWT_SECRET = os.environ["SUPERSET_GUEST_TOKEN_SECRET"]' in CONFIG
    assert "SUPERSET_GUEST_TOKEN_SECRET: ${SUPERSET_GUEST_TOKEN_SECRET:?" in (REPO / "docker-compose.yml").read_text()
    assert "SUPERSET_GUEST_TOKEN_SECRET=" in (REPO / ".env.example").read_text()


def test_the_login_redirect_keeps_the_whole_next_url():
    """next goes back into the URL encoded: unencoded, a next with its own query would lose all but its
    first parameter."""
    assert 'f"{target}?next={nxt}"' not in CONFIG
    assert 'url_for("AuthOAuthView.login", provider=provider, next=nxt)' in CONFIG


@pytest.mark.parametrize("path", compose_files(), ids=lambda p: p.name)
def test_every_compose_file_loads(path):
    """The refusals' messages read `see .env.example: openssl rand -hex 32`: a ": " inside a plain YAML value,
    so the standalone docker-compose.yml did not load at all (`docker compose config`: mapping values are not
    allowed in this context)."""
    import yaml

    assert isinstance(yaml.safe_load(path.read_text()), dict)
