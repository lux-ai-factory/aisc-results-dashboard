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
    """.env.example set IMMUDB_PASSWORD twice, empty under 'no defaults' and `immudb` under the audit
    ledger; the later line wins, so a copied .env ran on the default (docs pass 2026-10-03)."""
    names = [line.split("=", 1)[0] for line in (REPO / ".env.example").read_text().splitlines()
             if re.match(r"^[A-Z_][A-Z0-9_]*=", line)]
    assert sorted({n for n in names if names.count(n) > 1}) == []
    values = dict(line.split("=", 1) for line in (REPO / ".env.example").read_text().splitlines()
                  if re.match(r"^[A-Z_][A-Z0-9_]*=", line))
    assert values["IMMUDB_PASSWORD"] == ""


def test_the_audit_clerk_has_no_password_of_its_own(monkeypatch):
    """Without IMMUDB_PASSWORD it has none: it used `immudb`, the image's own default."""
    from aisc_ext.audit import clerk_kwargs_from_env

    monkeypatch.delenv("IMMUDB_PASSWORD", raising=False)
    assert clerk_kwargs_from_env()["password"] == ""


CONFIG = (REPO / "superset_config.py").read_text()


def test_the_config_has_no_fallback_oidc_client_secret():
    """OIDC_CLIENT_SECRET fell back to `superset-secret` (security review 2026-10-05): with AISC_OAUTH=1
    and no secret set, the dashboard ran its Keycloak login on a value anyone could read."""
    assert "superset-secret" not in CONFIG
    assert 'os.environ["OIDC_CLIENT_SECRET"]' in CONFIG


def test_guest_tokens_are_signed_with_a_secret_of_this_install():
    """EMBEDDED_SUPERSET is on, and GUEST_TOKEN_JWT_SECRET was never set, so Superset's published
    default signed guest tokens (security review 2026-10-05)."""
    assert 'GUEST_TOKEN_JWT_SECRET = os.environ["SUPERSET_GUEST_TOKEN_SECRET"]' in CONFIG
    assert "SUPERSET_GUEST_TOKEN_SECRET: ${SUPERSET_GUEST_TOKEN_SECRET:?" in (REPO / "docker-compose.yml").read_text()
    assert "SUPERSET_GUEST_TOKEN_SECRET=" in (REPO / ".env.example").read_text()


def test_the_login_redirect_keeps_the_whole_next_url():
    """next was put back into the URL unencoded, so a next with its own query lost all but its first
    parameter (code review 2026-10-05)."""
    assert 'f"{target}?next={nxt}"' not in CONFIG
    assert 'url_for("AuthOAuthView.login", provider=provider, next=nxt)' in CONFIG
