from pathlib import Path

from hey.domain.entities.sandbox import FileSystemPolicy, FileSystemRule, NetworkPolicy, PermissionProfile
from hey.infrastructure.sandbox.runners.macos import build_seatbelt_profile


def test_build_seatbelt_profile_allows_workspace_write_and_denies_network() -> None:
    project = Path("/tmp/project").resolve()
    profile = PermissionProfile(
        filesystem=FileSystemPolicy(
            mode="workspace_write",
            entries=(FileSystemRule(path=project, access="write"),),
        ),
        network=NetworkPolicy(mode="restricted"),
    )

    seatbelt = build_seatbelt_profile(profile, project)

    assert f'(allow file-read* (subpath "{project}"))' in seatbelt
    assert f'(allow file-write* (subpath "{project}"))' in seatbelt
    assert f'(deny file-write* (subpath "{project / ".git"}"))' in seatbelt
    assert f'(deny file-write* (subpath "{project / ".hey"}"))' in seatbelt
    assert "(deny network*)" in seatbelt


def test_build_seatbelt_profile_allows_network_when_enabled() -> None:
    project = Path("/tmp/project").resolve()
    profile = PermissionProfile(
        filesystem=FileSystemPolicy(
            mode="read_only",
            entries=(FileSystemRule(path=project, access="read"),),
        ),
        network=NetworkPolicy(mode="enabled"),
    )

    seatbelt = build_seatbelt_profile(profile, project)

    assert f'(allow file-read* (subpath "{project}"))' in seatbelt
    assert f'(allow file-write* (subpath "{project}"))' not in seatbelt
    assert "(allow network*)" in seatbelt
