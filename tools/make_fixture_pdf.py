#!/usr/bin/env python3
"""Write a minimal, deterministic, text-only PDF fixture.

Same shape as the hand-built fixtures under attachments/synthetic/: one
page, Helvetica, one text line per input line, a correct xref table, no
active content (so it passes the inert marker scan). Identical input always
produces identical bytes, so sha256 / doc_id in attachments/manifest.csv
stay stable.

Usage:
  python3 tools/make_fixture_pdf.py OUT.pdf "line one" "line two" ...
Prints the sha256 and doc_id (first 16 hex) of the written file.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf(lines: list[str]) -> bytes:
    stream = "".join(
        f"BT /F1 11 Tf 72 {720 - 16 * i} Td ({_escape(line)}) Tj ET\n"
        for i, line in enumerate(lines)
    ).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
        + stream + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for n, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    data = build_pdf(argv[2:])
    Path(argv[1]).write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    print(f"{digest} {digest[:16]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
