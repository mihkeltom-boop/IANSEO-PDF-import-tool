"""
Web interface for archery_parser.

Provides a Flask application with:
  - GET  /         → HTML upload form
  - POST /convert  → accepts PDF file(s), returns CSV download
  - GET  /health   → health check endpoint for Railway

The pipeline stages (reader → detector → assembler → transformer → writer)
are reused directly; only the I/O wrapper differs from the CLI.
"""

from __future__ import annotations

import csv
import io
import logging
import os
import tempfile
from pathlib import Path

from flask import Flask, request, send_file, render_template_string

from archery_parser.assembler import assemble_athletes
from archery_parser.detector import detect_sections
from archery_parser.reader import extract_lines
from archery_parser.transformer import transform
from archery_parser.writer import _HEADERS, _group_by_athlete, _verify_athlete_group

logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB upload limit


def _process_pdf_bytes(pdf_bytes: bytes, filename: str) -> tuple:
    """
    Run the pipeline on in-memory PDF bytes.

    Writes bytes to a temp file (pdfplumber requires a file path),
    then runs reader → detector → assembler.

    Returns:
        (CompetitionMeta, list[AthleteRecord])

    Raises:
        ValueError on parse failures.
    """
    if not pdf_bytes:
        raise ValueError("Uploaded file is empty (0 bytes).")

    logger.info("web  Received %s (%d bytes)", filename, len(pdf_bytes))

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp.flush()
        tmp_path = Path(tmp.name)

    try:
        lines = extract_lines(tmp_path)
        logger.info("web  reader: %d lines extracted from %s", len(lines), filename)

        if not lines:
            raise ValueError(
                f"No text could be extracted from '{filename}'. "
                "The PDF may be image-based (scanned) rather than text-based."
            )

        meta, sections = detect_sections(lines)
        logger.info(
            "web  detector: %d sections found in %s", len(sections), filename
        )

        if not sections:
            # Log the first few lines for debugging
            sample = []
            for line in lines[:10]:
                sample.append(" ".join(w.text for w in line))
            logger.warning(
                "web  No sections detected. First 10 lines: %s", sample
            )
            raise ValueError(
                f"No competition sections found in '{filename}'. "
                "Make sure this is an Ianseo qualification protocol PDF."
            )

        records = assemble_athletes(sections)
        logger.info(
            "web  assembler: %d athletes found in %s", len(records), filename
        )

        return meta, records
    finally:
        tmp_path.unlink(missing_ok=True)


def _rows_to_csv_bytes(rows) -> bytes:
    """Serialize CSVRow objects to UTF-8 CSV bytes."""
    # Run arithmetic verification (logs warnings but never suppresses rows).
    for group in _group_by_athlete(rows):
        _verify_athlete_group(group)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(_HEADERS)
    for row in rows:
        writer.writerow(row.as_row())
    return output.getvalue().encode("utf-8")


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_UPLOAD_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>IANSEO PDF Import Tool</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #f5f5f5;
            color: #333;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .container {
            background: #fff;
            border-radius: 8px;
            box-shadow: 0 2px 12px rgba(0,0,0,0.1);
            padding: 2rem;
            max-width: 520px;
            width: 90%;
        }
        h1 { font-size: 1.5rem; margin-bottom: 0.5rem; }
        p.subtitle { color: #666; margin-bottom: 1.5rem; font-size: 0.95rem; }
        form { display: flex; flex-direction: column; gap: 1rem; }
        label { font-weight: 600; font-size: 0.9rem; }
        input[type="file"] {
            border: 2px dashed #ccc;
            border-radius: 6px;
            padding: 1.5rem;
            text-align: center;
            cursor: pointer;
            background: #fafafa;
        }
        input[type="file"]:hover { border-color: #888; }
        button {
            background: #2563eb;
            color: #fff;
            border: none;
            border-radius: 6px;
            padding: 0.75rem 1.5rem;
            font-size: 1rem;
            cursor: pointer;
            font-weight: 600;
        }
        button:hover { background: #1d4ed8; }
        button:disabled { background: #93c5fd; cursor: not-allowed; }
        .error {
            background: #fef2f2;
            border: 1px solid #fca5a5;
            color: #991b1b;
            padding: 0.75rem 1rem;
            border-radius: 6px;
            font-size: 0.9rem;
        }
        .info {
            background: #eff6ff;
            border: 1px solid #93c5fd;
            color: #1e40af;
            padding: 0.75rem 1rem;
            border-radius: 6px;
            font-size: 0.85rem;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>IANSEO PDF Import Tool</h1>
        <p class="subtitle">
            Upload Ianseo archery qualification protocol PDFs to convert them
            into structured CSV files.
        </p>
        {% if error %}
        <div class="error">{{ error }}</div>
        {% endif %}
        <form method="POST" action="/convert" enctype="multipart/form-data">
            <label for="pdfs">Select PDF file(s)</label>
            <input type="file" id="pdfs" name="pdfs" accept=".pdf"
                   multiple required>
            <div class="info">
                You can select multiple PDF files. They will be combined
                into a single CSV output.
            </div>
            <button type="submit">Convert to CSV</button>
        </form>
    </div>
</body>
</html>
"""


@app.route("/")
def index():
    """Serve the upload form."""
    error = request.args.get("error")
    return render_template_string(_UPLOAD_HTML, error=error)


@app.route("/convert", methods=["POST"])
def convert():
    """Accept PDF upload(s), return CSV download."""
    files = request.files.getlist("pdfs")
    if not files or all(f.filename == "" for f in files):
        return render_template_string(_UPLOAD_HTML, error="No files selected."), 400

    all_rows = []
    first_meta = None
    filenames_processed = []

    for file in files:
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            return render_template_string(
                _UPLOAD_HTML,
                error=f"File '{file.filename}' is not a PDF.",
            ), 400

        try:
            pdf_bytes = file.read()
            meta, records = _process_pdf_bytes(pdf_bytes, file.filename)
        except (ValueError, Exception) as exc:
            logger.exception("Error processing %s", file.filename)
            return render_template_string(
                _UPLOAD_HTML,
                error=f"Error processing '{file.filename}': {exc}",
            ), 400

        if first_meta is None:
            first_meta = meta

        if not records:
            return render_template_string(
                _UPLOAD_HTML,
                error=f"No athletes could be parsed from '{file.filename}'. "
                      f"The PDF was read successfully ({meta.name}) but no "
                      f"athlete data was found in the detected sections.",
            ), 400

        rows = transform(records, meta)
        all_rows.extend(rows)
        filenames_processed.append(file.filename)

        logger.info(
            "web  Processed %s → %d athletes, %d rows",
            file.filename, len(records), len(rows),
        )

    if not all_rows:
        return render_template_string(
            _UPLOAD_HTML,
            error="No data rows were produced from the uploaded file(s).",
        ), 400

    csv_bytes = _rows_to_csv_bytes(all_rows)

    # Derive output filename from the first uploaded PDF.
    base_name = Path(filenames_processed[0]).stem
    output_name = f"{base_name}.csv"

    return send_file(
        io.BytesIO(csv_bytes),
        mimetype="text/csv",
        as_attachment=True,
        download_name=output_name,
    )


@app.route("/health")
def health():
    """Health check endpoint for Railway."""
    return {"status": "ok"}, 200


def create_app():
    """Application factory for gunicorn / Railway."""
    log_level = os.environ.get("LOG_LEVEL", "DEBUG").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.DEBUG),
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return app
