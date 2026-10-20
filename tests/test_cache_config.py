"""Superset's cache was the stack's shared `redis`, which
has no password and which the eval worker (where third-party plugin code runs) also reaches. cachelib unpickles
every value it reads from a RedisCache whose bytes start with "!", so a plugin that overwrote a `flask_cache_*`
key got code execution in the dashboard at the next page load.

The cache now reads a Redis of its own, named by DASHBOARD_REDIS_HOST / DASHBOARD_REDIS_PORT /
DASHBOARD_REDIS_PASSWORD (the shared REDIS_HOST is never read), and the dashboard refuses to start when that
Redis has no password."""
import re
from pathlib import Path

import pytest
import yaml

from aisc_ext.cache import cache_config

REPO = Path(__file__).resolve().parents[1]


def test_the_cache_refuses_a_redis_without_a_password():
    for env in ({}, {"DASHBOARD_REDIS_HOST": "dashboard-redis"},
                {"DASHBOARD_REDIS_HOST": "dashboard-redis", "DASHBOARD_REDIS_PASSWORD": "  "}):
        with pytest.raises(RuntimeError, match="DASHBOARD_REDIS_PASSWORD"):
            cache_config(env)


def test_the_cache_reads_its_own_redis_with_its_password():
    config = cache_config({"DASHBOARD_REDIS_HOST": "dashboard-redis", "DASHBOARD_REDIS_PORT": "6380",
                           "DASHBOARD_REDIS_PASSWORD": "s3cret"})
    assert config["CACHE_TYPE"] == "RedisCache"
    assert (config["CACHE_REDIS_HOST"], config["CACHE_REDIS_PORT"]) == ("dashboard-redis", 6380)
    assert config["CACHE_REDIS_PASSWORD"] == "s3cret"
    assert config["CACHE_KEY_PREFIX"]                                   # its keys are its own, by name too


def test_the_shared_redis_of_the_stack_is_never_the_cache():
    """The stack's environment still says REDIS_HOST=redis (the shared one): it must not be picked up."""
    config = cache_config({"REDIS_HOST": "redis", "REDIS_PORT": "6379", "DASHBOARD_REDIS_PASSWORD": "s3cret"})
    assert config["CACHE_REDIS_HOST"] != "redis"


def test_superset_config_takes_its_cache_from_there():
    text = (REPO / "superset_config.py").read_text()
    assert "CACHE_CONFIG = cache_config(os.environ)" in text
    assert 'os.environ.get("REDIS_HOST"' not in text


def test_the_standalone_stack_runs_its_redis_with_the_password():
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text())
    env = compose["x-superset-env"]
    host = env["DASHBOARD_REDIS_HOST"]
    assert re.fullmatch(r"\$\{DASHBOARD_REDIS_PASSWORD:\?[^}]+\}", env["DASHBOARD_REDIS_PASSWORD"])
    assert "DASHBOARD_REDIS_PASSWORD" in compose["services"][host]["environment"]
    example = (REPO / ".env.example").read_text()
    assert re.search(r"^DASHBOARD_REDIS_PASSWORD=$", example, re.M)
    assert "DASHBOARD_REDIS_PASSWORD" in (REPO / "scripts/bootstrap.sh").read_text()


def _run_redis_service(tmp_path, service: dict, password: str) -> tuple[list[str], str]:
    """Run the service's entrypoint + command as its container would (compose's $$ is a $), with a fake
    redis-server on PATH that records its arguments; /tmp/redis.conf is moved into tmp_path."""
    import os
    import subprocess

    as_list = lambda v: [] if v is None else ([v] if isinstance(v, str) else list(v))  # noqa: E731
    argv = [a.replace("$$", "$").replace("/tmp/redis.conf", str(tmp_path / "redis.conf"))
            for a in as_list(service.get("entrypoint")) + as_list(service.get("command"))]
    if not service.get("entrypoint"):                                   # the image's: redis-server's wrapper
        argv = ["sh", "-c", 'exec "$@"', "sh", *argv]
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "redis-server").write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$ARGS_OUT"\n')
    (fake / "redis-server").chmod(0o755)
    out = tmp_path / "args"
    env = {"PATH": f"{fake}:{os.environ['PATH']}", "DASHBOARD_REDIS_PASSWORD": password, "ARGS_OUT": str(out)}
    subprocess.run(argv, env=env, check=True, timeout=10)
    args = out.read_text().splitlines()
    conf = next((Path(a).read_text() for a in args if a.endswith(".conf") and Path(a).is_file()), "")
    return args, conf


def test_the_standalone_redis_password_is_not_on_its_command_line(tmp_path):
    """`redis-server --requirepass "$DASHBOARD_REDIS_PASSWORD"` put the password in the
    server's argv, which `ps` and /proc/<pid>/cmdline show on the host. Like the root compose's
    dashboard-redis, it now goes through a config file."""
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text())
    service = compose["services"][compose["x-superset-env"]["DASHBOARD_REDIS_HOST"]]
    args, conf = _run_redis_service(tmp_path, service, "pw-0123456789abcdef")
    assert not any("pw-0123456789abcdef" in a for a in args), "the password is in redis-server's argv"
    assert re.search(r"^requirepass pw-0123456789abcdef$", conf, re.M)
