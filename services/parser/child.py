"""Fixed parser child; Linux resource limits and seccomp deny network syscalls."""

import ctypes
import os
from pathlib import Path, PurePosixPath
import platform
import stat
import sys
import warnings
import zipfile

MAX_OUTPUT = 1024**2


def sandbox():
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (60, 65))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024**2, 512 * 1024**2))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT, MAX_OUTPUT))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    blocked = {
        "x86_64": (41, 42, 44, 46, 53, 57, 58, 425, 426, 427),
        "aarch64": (198, 199, 203, 206, 211, 425, 426, 427),
    }.get(platform.machine())
    if blocked is None:
        raise RuntimeError("unsupported_sandbox_architecture")

    class Filter(ctypes.Structure):
        _fields_ = [
            ("code", ctypes.c_ushort),
            ("jt", ctypes.c_ubyte),
            ("jf", ctypes.c_ubyte),
            ("k", ctypes.c_uint),
        ]

    class Program(ctypes.Structure):
        _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.POINTER(Filter))]

    # syscall numbers are architecture-specific; deny x32 ABI bypass as well.
    architecture = {"x86_64": 0xC000003E, "aarch64": 0xC00000B7}[platform.machine()]
    instructions = [
        Filter(0x20, 0, 0, 4),
        Filter(0x15, 1, 0, architecture),
        Filter(0x06, 0, 0, 0x80000000),
        Filter(0x20, 0, 0, 0),
        Filter(0x35, 0, 1, 0x40000000),
        Filter(0x06, 0, 0, 0x00050001),
    ]
    # clone3 is denied with ENOSYS so libc may fall back to clone for threads.
    # Only CLONE_THREAD can pass: no independent process may outlive this job.
    clone = {"x86_64": 56, "aarch64": 220}[platform.machine()]
    instructions.extend(
        [
            Filter(0x15, 0, 1, 435),
            Filter(0x06, 0, 0, 0x00050026),
            Filter(0x15, 0, 3, clone),
            Filter(0x20, 0, 0, 16),
            Filter(0x45, 1, 0, 0x00010000),
            Filter(0x06, 0, 0, 0x00050001),
            Filter(0x20, 0, 0, 0),
        ]
    )
    for syscall in blocked:
        instructions.extend(
            [Filter(0x15, 0, 1, syscall), Filter(0x06, 0, 0, 0x00050001)]
        )
    instructions.append(Filter(0x06, 0, 0, 0x7FFF0000))
    filters = (Filter * len(instructions))(*instructions)
    program = Program(len(filters), filters)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0) or libc.prctl(22, 2, ctypes.byref(program), 0, 0):
        raise RuntimeError("sandbox_unavailable")


def validate_docx(path):
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        names = [item.filename for item in entries]
        compressed = sum(item.compress_size for item in entries) or 1
        expanded = sum(item.file_size for item in entries)
        if (
            len(entries) > 2000
            or len(names) != len(set(names))
            or expanded > 50 * 1024**2
            or expanded / compressed > 100
        ):
            raise ValueError("unsafe_archive_expansion")
        if not {"[Content_Types].xml", "word/document.xml"}.issubset(names):
            raise ValueError("invalid_docx_structure")
        for item in entries:
            name = item.filename
            if (
                "\\" in name
                or ":" in name
                or PurePosixPath(name).is_absolute()
                or ".." in PurePosixPath(name).parts
                or any(ord(c) < 32 for c in name)
                or stat.S_ISLNK(item.external_attr >> 16)
                or item.flag_bits & 1
            ):
                raise ValueError("unsafe_archive_entry")
            if name.endswith(".xml") or name.endswith(".rels"):
                data = archive.read(item)
                if (
                    b"<!DOCTYPE" in data.upper()
                    or b"<!ENTITY" in data.upper()
                    or b'TargetMode="External"' in data
                ):
                    raise ValueError("unsafe_xml_reference")


def extract(path, mime):
    import magic

    with open(path, "rb") as source:
        actual = magic.from_buffer(source.read(8192), mime=True)
    if actual != mime:
        raise ValueError("mime_mismatch")
    remaining = MAX_OUTPUT

    def emit(text):
        nonlocal remaining
        data = text.encode("utf-8")
        remaining -= len(data)
        if remaining < 0:
            raise ValueError("output_limit")
        sys.stdout.buffer.write(data)

    if mime == "application/pdf":
        import pymupdf

        with pymupdf.open(path) as document:
            if document.needs_pass or document.page_count > 300:
                raise ValueError("pdf_limits")
            for page in document:
                emit(page.get_text("text") + "\n")
    elif (
        mime
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ):
        validate_docx(path)
        from docx import Document

        document = Document(path)
        for paragraph in document.paragraphs:
            emit(paragraph.text + "\n")
    elif mime in {"image/jpeg", "image/png"}:
        from PIL import Image

        Image.MAX_IMAGE_PIXELS = 10_000_000
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(path) as image:
            image.verify()
        # Replace the confined process. Spawning a subprocess would require
        # allowing fork and let a parser exploit persist into the next upload.
        os.execve(
            "/usr/bin/tesseract",
            ["/usr/bin/tesseract", path, "stdout", "-l", "por"],
            {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "OMP_THREAD_LIMIT": "1"},
        )
    elif mime == "text/plain":
        with open(path, "rb") as source:
            emit(source.read(MAX_OUTPUT + 1).decode("utf-8", errors="strict"))
    else:
        raise ValueError("unsupported_mime")


if __name__ == "__main__":
    sandbox()
    if len(sys.argv) != 3 or not Path(sys.argv[1]).is_file():
        raise SystemExit(2)
    extract(sys.argv[1], sys.argv[2])
