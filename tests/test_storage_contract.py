"""Atomic upload, deduplication and temporary cleanup in an isolated directory."""
import bz2
import io
from pathlib import Path

import pytest
from werkzeug.datastructures import FileStorage

from app.services.matchmaking import storage


@pytest.fixture
def isolated_storage(app, tmp_path):
    app.config.update(MATCHMAKING_STORAGE_DIR=str(tmp_path), MATCHMAKING_INBOX_DIR=str(tmp_path / "inbox"))
    return tmp_path


@pytest.mark.parametrize("content,limit,message", [
    (b'', 10, "está vacío"), (b'1234', 3, "tamaño máximo"),
])
def test_failed_upload_cleans_partial_file(isolated_storage, monkeypatch, content, limit, message):
    monkeypatch.setattr(storage, "_max_bytes", lambda: limit)
    file = FileStorage(stream=io.BytesIO(content), filename="demo.dem")
    with pytest.raises(storage.StorageError, match=message):
        storage.save_upload(1, file)
    assert list((isolated_storage / "inbox" / "1").iterdir()) == []


def test_upload_and_repeated_content_keep_one_archive(isolated_storage):
    first = storage.save_upload(1, FileStorage(stream=io.BytesIO(b'demo'), filename="one.dem"))
    first_result = storage.scan_inbox()[0]
    storage.save_upload(1, FileStorage(stream=io.BytesIO(b'demo'), filename="two.dem"))
    duplicate = storage.scan_inbox()[0]
    assert (first_result["duplicate"], duplicate["duplicate"]) == (False, True)
    assert (duplicate["path"], duplicate["sha256"]) == (first_result["path"], first_result["sha256"])
    assert not Path(first).exists()
    assert Path(duplicate["path"]).read_bytes() == b'demo'


def test_scanner_ignores_partial_files_and_invalid_user_folders(isolated_storage):
    storage.ensure_dirs()
    user_dir = Path(storage.user_inbox(1))
    (user_dir / "demo.dem.part").write_bytes(b'partial')
    invalid_user = isolated_storage / "inbox" / "not-a-user"
    invalid_user.mkdir()
    (invalid_user / "demo.dem").write_bytes(b'ignore')
    assert storage.scan_inbox() == []
    assert (user_dir / "demo.dem.part").exists()


def test_unreadable_inbox_file_is_retained_for_retry(isolated_storage, monkeypatch):
    path = storage.save_upload(1, FileStorage(stream=io.BytesIO(b'demo'), filename="demo.dem"))
    def unreadable(path):
        raise OSError("locked")
    monkeypatch.setattr(storage, "sha256_file", unreadable)
    assert storage.scan_inbox() == []
    assert Path(path).exists()


def test_decompression_cleans_temporary_on_consumer_failure(isolated_storage):
    storage.ensure_dirs()
    compressed = isolated_storage / "demos" / "sample.dem.bz2"
    compressed.write_bytes(bz2.compress(b'demo-content'))
    with pytest.raises(RuntimeError, match="consumer failure"):
        with storage.prepared_demo(str(compressed)) as path:
            assert Path(path).read_bytes() == b'demo-content'
            raise RuntimeError("consumer failure")
    assert not Path(path).exists()
    assert compressed.exists()


def test_corrupt_compressed_demo_is_controlled_and_cleaned(isolated_storage):
    storage.ensure_dirs()
    compressed = isolated_storage / "demos" / "broken.dem.bz2"
    compressed.write_bytes(b'invalid compression')
    with pytest.raises(storage.StorageError, match="descomprimir"):
        with storage.prepared_demo(str(compressed)):
            pytest.fail("A corrupt demo must never be yielded")
    assert list((isolated_storage / "demos").iterdir()) == [compressed]
