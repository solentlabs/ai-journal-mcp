import tarfile

import pytest

from ai_journal.archive import ArchiveError, archive_and_remove, verify_archive


def _make_tree(tmp_path):
    src = tmp_path / "logs"
    (src / "sub").mkdir(parents=True)
    (src / "a.md").write_text("alpha")
    (src / "sub" / "b.md").write_text("beta")
    return src


def test_archive_and_remove_dir(tmp_path):
    src = _make_tree(tmp_path)
    archive = archive_and_remove(src)
    assert archive == tmp_path / "logs.tar.gz"
    assert not src.exists()  # originals removed
    with tarfile.open(archive, "r:gz") as tar:
        names = set(tar.getnames())
    assert {"logs/a.md", "logs/sub/b.md"} <= names  # original tree preserved


def test_archive_and_remove_file(tmp_path):
    f = tmp_path / "note.md"
    f.write_text("hi")
    archive = archive_and_remove(f)
    assert archive == tmp_path / "note.md.tar.gz"
    assert not f.exists()
    with tarfile.open(archive, "r:gz") as tar:
        assert tar.getnames() == ["note.md"]


def test_refuses_to_overwrite_existing_archive(tmp_path):
    src = _make_tree(tmp_path)
    (tmp_path / "logs.tar.gz").write_text("pre-existing")
    with pytest.raises(ArchiveError, match="already exists"):
        archive_and_remove(src)
    assert src.exists()  # nothing removed


def test_verify_archive_detects_missing(tmp_path):
    src = _make_tree(tmp_path)
    archive = tmp_path / "partial.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:  # deliberately omit sub/b.md
        tar.add(src / "a.md", arcname="logs/a.md")
    assert verify_archive(archive, {"logs/a.md", "logs/sub/b.md"}) == {"logs/sub/b.md"}


def test_aborts_without_deleting_when_verify_fails(tmp_path, monkeypatch):
    # The safety net: if verification reports any missing file, the original
    # must survive. (Previously unreachable in a test; the extraction makes it
    # a one-line monkeypatch of the now-separate verify step.)
    src = _make_tree(tmp_path)
    monkeypatch.setattr("ai_journal.archive.verify_archive", lambda *a, **k: {"logs/a.md"})
    with pytest.raises(ArchiveError, match="missing"):
        archive_and_remove(src)
    assert src.exists()  # originals intact despite the archive existing
