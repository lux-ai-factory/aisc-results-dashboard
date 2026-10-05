"""The image's versions (security review 2026-10-05): Superset 4.1.1 had CVE-2025-27696 (a reader taking
ownership of dashboards, charts and datasets), fixed in 4.1.2; 4.1.4 is the last 4.1. Authlib was
installed unpinned, and an unpinned install keeps whatever the base image has; from 1.6.12 it carries
the fixes of CVE-2026-28802, CVE-2026-27962 and CVE-2026-44681. The pins are what the image ran."""
import re
from pathlib import Path

DOCKERFILE = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text()


def test_superset_is_the_last_41_release():
    assert re.search(r"^FROM apache/superset:4\.1\.4$", DOCKERFILE, re.M)


def test_every_added_package_is_pinned_and_authlib_carries_the_fixes():
    line = next(row for row in DOCKERFILE.splitlines() if "pip install" in row)
    packages = line.split("pip install", 1)[1].split()
    packages = [p for p in packages if not p.startswith("-")]
    assert packages and all("==" in p for p in packages), packages
    authlib = next(p for p in packages if p.lower().startswith("authlib=="))
    major, minor, patch = (int(x) for x in authlib.split("==")[1].split("."))
    assert (major, minor, patch) >= (1, 6, 12), authlib
