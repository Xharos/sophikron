"""Validate hostile file structures in a short-lived, resource-limited subprocess."""

import io
import os
import stat
import sys
import tokenize
import warnings
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

from defusedxml.ElementTree import fromstring
from PIL import Image
from pypdf import PdfReader

from app.core.documents import FILE_TYPES, MIB


def validate_archive(path: Path, extension: str) -> None:
    """Inspect bounded ZIP/Office structures without extracting or following embedded links.

    Parameters
    ----------
    path
        Private temporary file created by the upload service.
    extension
        Allowlisted archive or Office extension.
    """
    with ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > 1000 or sum(item.file_size for item in entries) > 100 * MIB:
            raise ValueError("Archive trop volumineuse après décompression.")
        names = set()
        for item in entries:
            name = item.orig_filename
            parts = PurePosixPath(name).parts
            if (
                name in names
                or "\\" in name
                or ":" in name
                or "\x00" in name
                or name.startswith("/")
                or ".." in parts
                or item.flag_bits & 1
                or stat.S_ISLNK(item.external_attr >> 16)
                or item.file_size > 25 * MIB
                or item.file_size > max(1, item.compress_size) * 200
            ):
                raise ValueError("Archive chiffrée ou structure non autorisée.")
            names.add(name)
            if name.lower().endswith((".zip", ".rar", ".7z", ".docm", ".xlsm", "vbaproject.bin")):
                raise ValueError("Archives imbriquées et macros non autorisées.")
            # Read every entry under the size bounds to verify decompression and CRC.
            with archive.open(item) as stream:
                while stream.read(65536):
                    pass
        if extension != "zip":
            main = "word/document.xml" if extension == "docx" else "xl/workbook.xml"
            for required in ("[Content_Types].xml", main):
                if required not in names or archive.getinfo(required).file_size > 2 * MIB:
                    raise ValueError("Structure Office invalide.")
                root = fromstring(archive.read(required))
                if any(
                    "macroenabled" in value.lower() or "vbaproject" in value.lower()
                    for node in root.iter()
                    for value in node.attrib.values()
                ):
                    raise ValueError("Les macros Office ne sont pas autorisées.")
            for name in names:
                if name.endswith(".rels"):
                    if archive.getinfo(name).file_size > MIB:
                        raise ValueError("Relations Office excessives.")
                    root = fromstring(archive.read(name))
                    if any(
                        node.attrib.get("TargetMode") == "External"
                        or "vbaproject" in node.attrib.get("Type", "").lower()
                        for node in root
                    ):
                        raise ValueError("Relations Office externes non autorisées.")


def validate_file(path: Path, extension: str) -> str:
    """Return the trusted MIME only after content validation; never execute uploaded code.

    Parameters
    ----------
    path
        File to inspect, stored outside the webroot.
    extension
        Validated extension selected by the server.

    Returns
    -------
    str
        MIME associated with the verified format.
    """
    if extension not in FILE_TYPES:
        raise ValueError("Format non autorisé.")
    if extension in {"jpg", "jpeg", "png"}:
        Image.MAX_IMAGE_PIXELS = 20_000_000
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path, formats=["JPEG", "PNG"]) as image:
                expected = "PNG" if extension == "png" else "JPEG"
                if (
                    image.format != expected
                    or max(image.size) > 12000
                    or image.width * image.height > 20_000_000
                ):
                    raise ValueError("Format ou dimensions de l’image non autorisés.")
                image.verify()
            with Image.open(path, formats=["JPEG", "PNG"]) as image:
                image.load()
    elif extension == "pdf":
        with path.open("rb") as stream:
            if not stream.read(8).startswith(b"%PDF-"):
                raise ValueError("PDF invalide.")
            stream.seek(0)
            reader = PdfReader(stream, strict=True)
            if reader.is_encrypted or len(reader.pages) > 3000:
                raise ValueError("PDF chiffré ou trop complexe.")
    elif extension in {"docx", "xlsx", "zip"}:
        validate_archive(path, extension)
    else:
        raw = path.read_bytes()
        encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
        content = raw.decode(encoding)
        if "\x00" in content:
            raise ValueError("Le fichier Python doit être un fichier texte.")
    return FILE_TYPES[extension][1]


def main() -> int:
    """Apply OS limits when available and emit only a MIME or a generic rejection."""
    if os.name == "posix":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (512 * MIB, 512 * MIB))
        resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    try:
        mime = validate_file(Path(sys.argv[1]), sys.argv[2])
    except Exception:
        # Parser diagnostics can contain document data; never echo them to the caller/logs.
        return 1
    print(mime)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
