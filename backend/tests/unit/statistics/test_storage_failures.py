"""Storage failure contracts without accessing persistent document data."""

from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.documents import DocumentSettings
from app.services.statistics import folder_usage


@pytest.mark.parametrize("folder", ["objects", "temporary"])
def test_unreadable_folder_reports_unavailable(tmp_path: Path, folder: str) -> None:
    """Report unavailable metering rather than a misleading zero on access failure."""
    (tmp_path / folder).mkdir()
    with patch("app.services.statistics.os.scandir", side_effect=PermissionError):
        assert folder_usage(DocumentSettings(root=tmp_path)) == (None, None)


def test_disappearing_file_does_not_break_metering(tmp_path: Path) -> None:
    """Ignore files removed between directory enumeration and metadata inspection."""
    from unittest.mock import MagicMock

    (tmp_path / "objects").mkdir()
    entry = MagicMock()
    entry.stat.side_effect = FileNotFoundError
    entries = MagicMock()
    entries.__enter__.return_value = [entry]
    with patch("app.services.statistics.os.scandir", return_value=entries):
        assert folder_usage(DocumentSettings(root=tmp_path)) == (0, 0)


def test_symbolic_root_is_not_followed(tmp_path: Path) -> None:
    """Reject symbolic document roots before reading their contents."""
    with patch.object(Path, "is_symlink", return_value=True):
        assert folder_usage(DocumentSettings(root=tmp_path)) == (None, None)


def test_symbolic_managed_folder_is_not_followed(tmp_path: Path) -> None:
    """Reject a managed-folder link even when the root itself is regular."""
    with patch.object(Path, "is_symlink", side_effect=[False, True]):
        assert folder_usage(DocumentSettings(root=tmp_path)) == (None, None)


def test_regular_files_only_are_counted(tmp_path: Path) -> None:
    """Exclude subdirectories without recursively scanning unmanaged children."""
    folder = tmp_path / "objects"
    folder.mkdir()
    (folder / "nested").mkdir()
    (folder / "nested" / "ignored").write_bytes(b"x" * 20)
    (folder / "empty").touch()
    assert folder_usage(DocumentSettings(root=tmp_path)) == (0, 0)
