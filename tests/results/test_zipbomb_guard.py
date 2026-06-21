"""L4: verify_artifact must reject zip members whose file_size header exceeds the cap.

Engineering.md §5: artifact integrity. A zip bomb (oversized decompressed member)
must be detected from the central-directory header — before any bytes are read
into memory — and verification must fail with a clear message.

The test crafts a zip whose member's `file_size` field in both the local file
header and the central directory is patched to exceed MAX_MEMBER_BYTES without
actually materialising oversized bytes on disk (binary patching of the zip
structure). This proves the guard reads the header, not the data.
"""

import io
import json
import struct
import zipfile
from pathlib import Path

from copeca.results.verification import MAX_MEMBER_BYTES, verify_artifact


def _patch_zip_file_size(data: bytes, member_name: str, new_file_size: int) -> bytes:
    """Binary-patch the file_size field in both the local file header and
    the central directory entry for *member_name* inside *data*.

    Zip format references:
    - Local file header (LFH): signature PK\\x03\\x04, file_size at offset +22 (4 bytes LE)
    - Central directory file header (CDFH): signature PK\\x01\\x02,
      file_size at offset +24 (4 bytes LE)
    """
    encoded = member_name.encode()
    result = bytearray(data)

    # Patch local file headers
    pos = 0
    while True:
        pos = data.find(b"PK\x03\x04", pos)
        if pos == -1:
            break
        fname_len = struct.unpack_from("<H", data, pos + 26)[0]
        fname = data[pos + 30 : pos + 30 + fname_len]
        if fname == encoded:
            struct.pack_into("<I", result, pos + 22, new_file_size)
        pos += 1

    # Patch central directory entries
    pos = 0
    while True:
        pos = data.find(b"PK\x01\x02", pos)
        if pos == -1:
            break
        fname_len = struct.unpack_from("<H", data, pos + 28)[0]
        fname = data[pos + 46 : pos + 46 + fname_len]
        if fname == encoded:
            struct.pack_into("<I", result, pos + 24, new_file_size)
        pos += 1

    return bytes(result)


def _make_oversized_zip(output_path: Path) -> None:
    """Write a zip where result.json's file_size header exceeds MAX_MEMBER_BYTES.

    The actual bytes stored are tiny — only the header fields are binary-patched —
    so the test doesn't write gigabytes of data, but the guard must still reject it
    by reading the header before attempting to decompress.
    """
    real_content = b'{"task": "bomb_test"}'
    manifest_bytes = json.dumps(
        {"content_hash": "y" * 64, "files": {"result.json": "x" * 64}},
        sort_keys=True,
    ).encode("utf-8")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("result.json", real_content)
        zf.writestr("manifest.json", manifest_bytes)

    patched = _patch_zip_file_size(buf.getvalue(), "result.json", MAX_MEMBER_BYTES + 1)
    output_path.write_bytes(patched)


class TestZipBombGuard:
    def test_oversized_member_header_is_rejected(self, tmp_path: Path) -> None:
        """verify_artifact must return (False, <message>) when any member's
        file_size header exceeds MAX_MEMBER_BYTES — without reading the member.

        If MAX_MEMBER_BYTES is not importable from verification.py, the fix
        has not been applied yet (ImportError → RED).
        """
        zip_path = tmp_path / "bomb.copeca.zip"
        _make_oversized_zip(zip_path)

        valid, message = verify_artifact(zip_path)

        assert valid is False, (
            "verify_artifact must reject a zip member whose file_size header "
            f"exceeds MAX_MEMBER_BYTES ({MAX_MEMBER_BYTES}). Got valid=True."
        )
        assert (
            "size" in message.lower() or "bomb" in message.lower() or "exceeds" in message.lower()
        ), f"Rejection message should mention size/bomb/exceeds; got: {message!r}"

    def test_normal_member_is_accepted(self, tmp_path: Path) -> None:
        """A zip with a member well within the size cap must still pass the guard."""
        from copeca.results.artifact import build_artifact

        record = {"task": "normal", "mode": "baseline", "model": "test", "repetition": 0}
        worktree = tmp_path / "wt"
        worktree.mkdir()
        output_dir = tmp_path / "out"
        output_dir.mkdir()

        zip_path = build_artifact(record, worktree, output_dir)
        valid, message = verify_artifact(zip_path)

        assert valid is True, f"Normal artifact should pass guard; got: {message}"
