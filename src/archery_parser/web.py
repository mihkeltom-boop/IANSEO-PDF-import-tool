"""
Minimal Flask web interface for Railway deployment.

Provides a single endpoint for uploading Ianseo PDF files and downloading
the parsed CSV result.

Routes:
    GET  /          — Upload form
    POST /convert   — Accept PDF upload, return CSV download
    GET  /health    — Health check for Railway
"""

from __future__ import annotations

import io
import logging
import tempfile
from pathlib import Path

from flask import Flask, request, send_file, render_template_string

from archery_parser.assembler import assemble_athletes
from archery_parser.detector import detect_sections
from archery_parser.reader import extract_lines
from archery_parser.transformer import transform
from archery_parser.writer import write_csv

app = Flask(__name__)
logger = logging.getLogger(__name__)

_UPLOAD_FORM = """\
<!DOCTYPE html>
<html>
<head><title>Ianseo PDF to CSV</title></head>
<body>
  <h1>Ianseo PDF to CSV Converter</h1>
  <form action="/convert" method="post" enctype="multipart/form-data">
    <input type="file" name="pdf" accept=".pdf" required>
    <button type="submit">Convert</button>
  </form>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(_UPLOAD_FORM)


@app.route("/health")
def health():
    return {"status": "ok"}


@app.route("/convert", methods=["POST"])
def convert():
    if "pdf" not in request.files:
        return "No file uploaded", 400

    pdf_file = request.files["pdf"]
    if not pdf_file.filename or not pdf_file.filename.lower().endswith(".pdf"):
        return "Please upload a PDF file", 400

    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / pdf_file.filename
        pdf_file.save(pdf_path)

        try:
            lines = extract_lines(pdf_path)
            meta, sections = detect_sections(lines)
            records = assemble_athletes(sections)
            rows = transform(records, meta)
        except (ValueError, Exception) as exc:
            logger.error("Failed to parse %s: %s", pdf_file.filename, exc)
            return f"Failed to parse PDF: {exc}", 400

        if not rows:
            return "No data found in PDF", 400

        csv_path = Path(tmpdir) / "output.csv"
        write_csv(rows, csv_path)

        csv_bytes = csv_path.read_bytes()

    output_name = Path(pdf_file.filename).stem + ".csv"
    return send_file(
        io.BytesIO(csv_bytes),
        mimetype="text/csv",
        as_attachment=True,
        download_name=output_name,
    )


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
