"""Export the tested runtime dependency versions and optionally check them against OSV.

Run inside the build venv so the lock reflects what the tests and the portable build used:

    .build\\venv\\Scripts\\python.exe packaging\\export_runtime_lock.py > requirements-lock.txt
    .build\\venv\\Scripts\\python.exe packaging\\export_runtime_lock.py --check-osv

The closure follows requirements.txt only; build tools stay in packaging/build-requirements.txt.
"""
import argparse
import json
import re
import sys
from importlib import metadata
from pathlib import Path
from urllib.request import Request, urlopen

try:
    from packaging.markers import default_environment
    from packaging.requirements import Requirement
except ImportError:  # any environment with pip can run this: fall back to pip's vendored copy
    from pip._vendor.packaging.markers import default_environment
    from pip._vendor.packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]
OSV_BATCH_URL = "https://api.osv.dev/v1/querybatch"


def runtime_closure(requirements_path):
    """Installed (name, version) pairs reachable from the top-level requirements."""
    environment = {**default_environment(), "extra": ""}
    pending = []
    for line in Path(requirements_path).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            pending.append(Requirement(line))
    seen = {}
    while pending:
        requirement = pending.pop()
        key = re.sub(r"[-_.]+", "-", requirement.name).lower()
        if key in seen:
            continue
        distribution = metadata.distribution(requirement.name)
        seen[key] = (distribution.metadata["Name"], distribution.version)
        for raw in distribution.requires or []:
            child = Requirement(raw)
            if child.marker is None or child.marker.evaluate(environment):
                pending.append(child)
    return [seen[key] for key in sorted(seen)]


def osv_advisories(pins):
    """{"name==version": [advisory ids]} for pins that have known advisories."""
    queries = [{"package": {"name": name, "ecosystem": "PyPI"}, "version": version} for name, version in pins]
    request = Request(OSV_BATCH_URL, data=json.dumps({"queries": queries}).encode("utf-8"),
                      headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=60) as response:
        results = json.load(response).get("results", [])
    return {f"{name}=={version}": [item["id"] for item in result.get("vulns", [])]
            for (name, version), result in zip(pins, results) if result.get("vulns")}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--requirements", default=str(ROOT / "requirements.txt"))
    parser.add_argument("--check-osv", action="store_true", help="query api.osv.dev for known advisories")
    args = parser.parse_args(argv)
    pins = runtime_closure(args.requirements)
    if args.check_osv:
        advisories = osv_advisories(pins)
        for pin, ids in advisories.items():
            print(f"{pin}: {', '.join(ids)}")
        print(f"{len(advisories)} of {len(pins)} pinned packages have OSV advisories")
        return 1 if advisories else 0
    for name, version in pins:
        print(f"{name}=={version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
