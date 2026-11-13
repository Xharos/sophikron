"""Statistics storage contracts."""

from pathlib import Path

from app.core.documents import DocumentSettings
from app.services.statistics import folder_usage


def test_statistics_measure_only_document_folders(tmp_path: Path) -> None:
    """Do not confuse whole-filesystem usage, unrelated root files or directories with documents."""
    settings = DocumentSettings(root=tmp_path)
    assert folder_usage(settings) == (0, 0)
    (tmp_path / "objects").mkdir()
    (tmp_path / "temporary").mkdir()
    (tmp_path / "objects" / "document").write_bytes(b"12345")
    (tmp_path / "objects" / "nested").mkdir()
    (tmp_path / "temporary" / "upload").write_bytes(b"123")
    (tmp_path / "unrelated").write_bytes(b"do not count")
    assert folder_usage(settings) == (5, 3)
