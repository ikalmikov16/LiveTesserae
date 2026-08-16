"""Guards on the committed ECS task definition template.

Two things went wrong with this file before: it was a
`describe-task-definition` dump, which `register-task-definition` rejects
outright, and it carried a live RDS password into a public repo's git history.
Both are the kind of mistake that comes back the next time someone pastes AWS
console output over it, so they are pinned here.
"""

import json
import re
from pathlib import Path

import pytest

TASK_DEF_PATH = Path(__file__).resolve().parents[2] / "task-def.json"

# Everything register-task-definition accepts at the top level.
REGISTERABLE_KEYS = {
    "family",
    "taskRoleArn",
    "executionRoleArn",
    "networkMode",
    "containerDefinitions",
    "volumes",
    "placementConstraints",
    "requiresCompatibilities",
    "cpu",
    "memory",
    "tags",
    "pidMode",
    "ipcMode",
    "proxyConfiguration",
    "inferenceAccelerators",
    "ephemeralStorage",
    "runtimePlatform",
    "enableFaultInjection",
}

# Read-only fields that only appear in a describe/dump, and make register fail.
DESCRIBE_ONLY_KEYS = {
    "taskDefinitionArn",
    "revision",
    "status",
    "requiresAttributes",
    "compatibilities",
    "registeredAt",
    "registeredBy",
    "deregisteredAt",
}


@pytest.fixture(scope="module")
def task_def() -> dict:
    return json.loads(TASK_DEF_PATH.read_text())


@pytest.fixture(scope="module")
def container(task_def) -> dict:
    containers = task_def["containerDefinitions"]
    assert len(containers) == 1, "single-instance app, single container"
    return containers[0]


def test_has_no_describe_only_fields(task_def):
    present = DESCRIBE_ONLY_KEYS & task_def.keys()
    assert not present, (
        f"{sorted(present)} are read-only fields from a describe dump; "
        "register-task-definition rejects them"
    )


def test_only_registerable_top_level_keys(task_def):
    unknown = task_def.keys() - REGISTERABLE_KEYS
    assert not unknown, f"unknown top-level keys: {sorted(unknown)}"


def test_no_inline_credentials(container):
    """The database URL must arrive via Secrets Manager, never as plaintext."""
    for entry in container.get("environment", []):
        assert entry["name"] != "DATABASE_URL", (
            "DATABASE_URL must be in `secrets` with a valueFrom ARN, not in "
            "`environment` — that is how the last password reached a public repo"
        )

    secrets = {s["name"]: s["valueFrom"] for s in container.get("secrets", [])}
    assert "DATABASE_URL" in secrets
    assert secrets["DATABASE_URL"].startswith("arn:aws:") or secrets[
        "DATABASE_URL"
    ].startswith("${"), "DATABASE_URL must reference a secret ARN"


def test_no_password_shaped_strings_anywhere():
    """Catch a credential pasted into any field, not just the ones we model."""
    raw = TASK_DEF_PATH.read_text()
    # postgres://user:password@host — the exact shape that leaked last time.
    assert not re.search(
        r"://[^/\s:]+:[^/\s@]+@", raw
    ), "task-def.json contains a URL with inline credentials"


def test_sets_trusted_proxy_hops(container):
    """At 0 behind a load balancer the per-IP caps become site-wide."""
    env = {e["name"]: e["value"] for e in container["environment"]}
    assert "TRUSTED_PROXY_HOPS" in env, (
        "TRUSTED_PROXY_HOPS must be set explicitly in production; omitting it "
        "defaults to 0, which caps the whole site at ws_max_connections_per_ip "
        "concurrent visitors"
    )
    assert env["TRUSTED_PROXY_HOPS"] != "0"


def test_placeholders_are_substitutable():
    """Every ${...} must be one register-task-def.sh knows how to fill."""
    raw = TASK_DEF_PATH.read_text()
    found = set(re.findall(r"\$\{([A-Z_]+)\}", raw))
    script = (TASK_DEF_PATH.parent / "register-task-def.sh").read_text()
    unhandled = {name for name in found if f"${{{name}}}" not in script}
    assert not unhandled, f"placeholders no script substitutes: {sorted(unhandled)}"
