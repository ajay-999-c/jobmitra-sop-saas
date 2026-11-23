"""Resume storage uses the existing private-handle policies on both platforms."""

import os
from unittest.mock import Mock

import pytest
from sqlalchemy.exc import SQLAlchemyError
from test_v12_proposal_storage import FakeWindowsApi

from jobmitra.modules.ats_v2 import proposal_storage as storage
from jobmitra.modules.ats_v2 import proposal_windows as win
from jobmitra.modules.ats_v2 import resume_storage, resumes
from jobmitra.modules.ats_v2.common import AtsError

KEY = "a" * 32 + ".docx"
RELATIVE = "4294967296/original/" + KEY


@pytest.mark.parametrize(
    "relative",
    [
        RELATIVE,
        "original/candidate_4294967296/" + KEY,
        "altered/candidate_4294967296/" + KEY,
        "parsed/candidate_4294967296/" + "a" * 32 + ".json",
    ],
)
def test_resume_exclusive_bytes_and_private_permissions(tmp_path, relative):
    root = tmp_path / "resumes"
    path = resume_storage.publish(root, relative, b"binary\x00fixture")
    assert resume_storage.read(root, relative) == b"binary\x00fixture"
    with pytest.raises((AtsError, OSError)):
        resume_storage.publish(root, relative, b"replacement")
    assert path.read_bytes() == b"binary\x00fixture"
    if os.name == "posix":
        assert path.stat().st_mode & 0o077 == 0


@pytest.mark.parametrize(
    "relative",
    [
        "../original/" + KEY,
        "/absolute/original/" + KEY,
        "C:/original/" + KEY,
        "429/original/" + KEY + ":ads",
        "429\\original\\" + KEY,
        "429/original/bad.docx",
    ],
)
def test_resume_paths_fail_closed(tmp_path, relative):
    with pytest.raises(AtsError):
        resume_storage.publish(tmp_path / "private", relative, b"x")
    assert not (tmp_path / "private").exists()


@pytest.mark.skipif(os.name != "posix", reason="Real POSIX filesystem attack checks")
@pytest.mark.parametrize("attack", ["parent_symlink", "leaf_symlink", "hardlink"])
def test_resume_filesystem_attacks_preserve_external_bytes(tmp_path, attack):
    root = tmp_path / "resumes"
    leaf = resume_storage.publish(root, RELATIVE, b"original")
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    victim = outside / KEY
    victim.write_bytes(b"private external")
    victim.chmod(0o600)
    if attack == "parent_symlink":
        leaf.unlink()
        leaf.parent.rmdir()
        leaf.parent.symlink_to(outside, target_is_directory=True)
    else:
        leaf.unlink()
        if attack == "leaf_symlink":
            leaf.symlink_to(victim)
        else:
            os.link(victim, leaf)
    with pytest.raises((AtsError, OSError)):
        resume_storage.read(root, RELATIVE)
    with pytest.raises((AtsError, OSError)):
        resume_storage.publish(root, RELATIVE, b"overwrite")
    assert victim.read_bytes() == b"private external"


def test_resume_windows_dispatch_with_missing_posix_flags_is_simulation(monkeypatch, tmp_path):
    api = FakeWindowsApi()
    monkeypatch.setattr(win, "path_parts", lambda root: ("C:\\", ("private", "proposals")))
    monkeypatch.setattr(storage, "PLATFORM", "nt")
    monkeypatch.setattr(
        storage,
        "_windows",
        lambda key_validator=storage.checked_key: win.WindowsStore(
            api, key_validator=key_validator
        ),
    )
    for flag in ["O_NOFOLLOW", "O_DIRECTORY"]:
        monkeypatch.delattr(storage.os, flag, raising=False)
    root = tmp_path / "resumes"
    resume_storage.publish(root, RELATIVE, b"docx fixture\x00")
    assert resume_storage.read(root, RELATIVE) == b"docx fixture\x00"
    with pytest.raises(AtsError):
        resume_storage.publish(root, RELATIVE, b"overwrite")
    resume_storage.remove(root, RELATIVE)
    assert api.files == {} and api.held == []


def test_uncertain_commit_cleanup_retains_bytes_on_database_failure(tmp_path):
    root = tmp_path / "resumes"
    path = resume_storage.publish(root, RELATIVE, b"retained evidence")
    engine = Mock()
    engine.connect.side_effect = SQLAlchemyError("unavailable")
    resumes.discard_unreferenced(engine, root, path)
    assert resume_storage.read(root, RELATIVE) == b"retained evidence"
