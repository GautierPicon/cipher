import secrets
import shutil
import tarfile
from collections.abc import Callable
from pathlib import Path

from cipher.crypto import decrypt_stream, encrypt_stream, verify_stream


class DestinationExistsError(Exception):
    pass


def default_enc_dest(src: Path) -> Path:
    if src.is_dir():
        return Path(str(src).rstrip("/") + ".enc")
    return src.with_suffix(".enc")


def encrypt_path(
    src: Path,
    password: str,
    dest: Path,
    on_progress: Callable[[int], None] | None = None,
) -> str:
    return encrypt_stream(src, password, dest, on_progress)


def decrypt_file(
    enc_path: Path,
    password: str,
    output: Path | None = None,
    on_progress: Callable[[int], None] | None = None,
    overwrite: bool = False,
    confirm_overwrite: Callable[[Path], bool] | None = None,
    resolve_dest: Callable[[Path], Path | None] | None = None,
) -> Path:
    """Decrypt ``enc_path`` and restore the authenticated original name.

    When the destination exists, ``resolve_dest(dest)`` is asked for
    first and may return a replacement path (rename) or ``None`` to
    cancel. Without it, ``confirm_overwrite(dest)`` is consulted;
    returning False cancels the operation. With neither callback,
    ``overwrite`` forces replacement; otherwise raises
    :class:`DestinationExistsError`.
    """
    tmp_dest = enc_path.parent / f".{secrets.token_hex(8)}.tmp"

    try:
        original_name, _ = decrypt_stream(enc_path, password, tmp_dest, on_progress)
        is_tar = original_name.endswith(".tar.gz")

        if is_tar:
            folder_name = original_name[: -len(".tar.gz")]
            dest = output or enc_path.parent / folder_name

            dest, replaces_existing = _resolve_conflict(
                dest, overwrite, confirm_overwrite, resolve_dest
            )
            if dest is None:
                return None

            staging = enc_path.parent / f".{secrets.token_hex(8)}.extract"
            staging.mkdir()
            try:
                extract_root = staging.resolve()
                with tarfile.open(tmp_dest, "r:gz") as tar:
                    for member in tar.getmembers():
                        member_path = (extract_root / member.name).resolve()
                        if not str(member_path).startswith(str(extract_root)):
                            raise ValueError(f"Unsafe path in archive: {member.name}")
                    tar.extractall(path=staging, filter="data")

                extracted = staging / folder_name
                if replaces_existing and dest.exists():
                    if dest.is_dir():
                        shutil.rmtree(dest)
                    else:
                        dest.unlink()
                extracted.rename(dest)
            finally:
                if staging.exists():
                    shutil.rmtree(staging)

            return dest

        dest = output or enc_path.parent / original_name

        dest, _replaces = _resolve_conflict(
            dest, overwrite, confirm_overwrite, resolve_dest
        )
        if dest is None:
            return None

        tmp_dest.rename(dest)
        return dest

    finally:
        if tmp_dest.exists():
            tmp_dest.unlink()


def _resolve_conflict(
    dest: Path,
    overwrite: bool,
    confirm_overwrite: Callable[[Path], bool] | None,
    resolve_dest: Callable[[Path], Path | None] | None,
) -> tuple[Path | None, bool]:
    """Return the final destination and whether it replaces an existing
    path. ``None`` destination means cancelled.
    """
    if not dest.exists():
        return dest, False
    if resolve_dest is not None:
        resolved = resolve_dest(dest)
        if resolved is None:
            return None, False
        return resolved, resolved == dest
    if confirm_overwrite is not None:
        if not confirm_overwrite(dest):
            return None, False
        return dest, True
    if overwrite:
        return dest, True
    raise DestinationExistsError(str(dest))


def verify_file(enc_path: Path, password: str) -> str:
    original_name, _ = verify_stream(enc_path, password)
    return original_name
