from pathlib import Path

from cipher.service import (
    DestinationExistsError,
    decrypt_file,
    default_enc_dest,
    encrypt_path,
)

PASSWORD = "StrongPass1!"


def _encrypt(src: Path) -> Path:
    enc = default_enc_dest(src)
    encrypt_path(src, PASSWORD, enc)
    return enc


def test_resolve_dest_not_called_without_conflict(tmp_path):
    src = tmp_path / "a.txt"
    src.write_bytes(b"a")
    enc = _encrypt(src)
    src.unlink()

    calls = []
    dest = decrypt_file(enc, PASSWORD, resolve_dest=lambda d: calls.append(d))
    assert dest == tmp_path / "a.txt"
    assert not calls


def test_rename_on_file_conflict(tmp_path):
    src = tmp_path / "doc.txt"
    src.write_bytes(b"v1")
    enc = _encrypt(src)

    resolved = tmp_path / "doc (2).txt"
    dest = decrypt_file(
        enc,
        PASSWORD,
        resolve_dest=lambda d: d.parent / "doc (2).txt",
    )
    assert dest == resolved
    assert dest.read_bytes() == b"v1"
    assert src.read_bytes() == b"v1"
    assert not list(tmp_path.glob(".*.tmp"))


def test_cancel_on_conflict_returns_none(tmp_path):
    src = tmp_path / "keep.txt"
    src.write_bytes(b"original")
    enc = _encrypt(src)

    result = decrypt_file(enc, PASSWORD, resolve_dest=lambda d: None)
    assert result is None
    assert src.read_bytes() == b"original"


def test_rename_on_folder_conflict(tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    (folder / "inside.txt").write_text("payload")
    enc = _encrypt(folder)

    existing = tmp_path / "data"
    assert existing.exists()

    dest = decrypt_file(
        enc,
        PASSWORD,
        resolve_dest=lambda d: d.parent / "data (1)",
    )
    assert dest == tmp_path / "data (1)"
    assert (dest / "inside.txt").read_text() == "payload"
    assert existing.exists()
    assert not list(tmp_path.glob(".*.tmp"))


def test_no_callback_and_no_overwrite_raises(tmp_path):
    src = tmp_path / "x.txt"
    src.write_bytes(b"x")
    enc = _encrypt(src)

    try:
        decrypt_file(enc, PASSWORD)
        raised = False
    except DestinationExistsError:
        raised = True
    assert raised
