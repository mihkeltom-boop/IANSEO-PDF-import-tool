"""
Minimal Flask web interface for Railway deployment.

Provides a UI for uploading Ianseo PDF files, previewing the first 20
parsed rows in a table, and displaying any warnings or errors from the
parsing pipeline.  The full CSV is still downloadable.

Routes:
    GET  /          — Upload form
    POST /convert   — Accept PDF upload, show preview + problems + download link
    GET  /download  — Download the last converted CSV
    GET  /health    — Health check for Railway
"""

from __future__ import annotations

import io
import logging
import tempfile
from pathlib import Path

from flask import Flask, request, send_file, render_template_string, session

from archery_parser.assembler import assemble_athletes
from archery_parser.detector import detect_sections
from archery_parser.reader import extract_lines
from archery_parser.transformer import transform
from archery_parser.writer import write_csv

app = Flask(__name__)
app.secret_key = "archery-parser-dev-key"
logger = logging.getLogger(__name__)

# In-memory store for the last converted CSV (single-user / demo use).
_last_csv: dict[str, bytes] = {}


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ianseo PDF to CSV</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: #f5f5f5; color: #1a1a1a; padding: 24px;
  }
  .container { max-width: 1100px; margin: 0 auto; }
  h1 { font-size: 1.6rem; margin-bottom: 8px; }
  .subtitle { color: #666; margin-bottom: 24px; font-size: 0.9rem; }

  /* Upload form */
  .upload-card {
    background: #fff; border-radius: 8px; padding: 20px;
    box-shadow: 0 1px 3px rgba(0,0,0,.1); margin-bottom: 24px;
  }
  .upload-card form { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
  .upload-card input[type=file] { font-size: 0.9rem; }
  .upload-card button {
    background: #2563eb; color: #fff; border: none; border-radius: 6px;
    padding: 8px 20px; font-size: 0.9rem; cursor: pointer;
  }
  .upload-card button:hover { background: #1d4ed8; }

  /* Stats bar */
  .stats {
    display: flex; gap: 24px; margin-bottom: 16px; flex-wrap: wrap;
  }
  .stat { background: #fff; border-radius: 8px; padding: 14px 20px;
          box-shadow: 0 1px 3px rgba(0,0,0,.08); min-width: 140px; }
  .stat .label { font-size: 0.75rem; color: #888; text-transform: uppercase; letter-spacing: .05em; }
  .stat .value { font-size: 1.4rem; font-weight: 600; margin-top: 2px; }
  .stat .value.ok { color: #16a34a; }
  .stat .value.bad { color: #dc2626; }

  /* Problems panel */
  .problems {
    background: #fff; border-radius: 8px; padding: 16px 20px;
    box-shadow: 0 1px 3px rgba(0,0,0,.08); margin-bottom: 24px;
  }
  .problems h2 { font-size: 1rem; margin-bottom: 10px; }
  .problems.has-problems { border-left: 4px solid #dc2626; }
  .problems.all-clear { border-left: 4px solid #16a34a; }
  .problem-list { list-style: none; max-height: 260px; overflow-y: auto; }
  .problem-list li {
    font-family: "SF Mono", "Consolas", monospace; font-size: 0.8rem;
    padding: 4px 0; border-bottom: 1px solid #f0f0f0; color: #b91c1c;
    word-break: break-word;
  }
  .problem-list li.info { color: #666; }

  /* Data table */
  .table-card {
    background: #fff; border-radius: 8px; padding: 16px 20px;
    box-shadow: 0 1px 3px rgba(0,0,0,.08); margin-bottom: 24px;
    overflow-x: auto;
  }
  .table-card h2 { font-size: 1rem; margin-bottom: 10px; }
  table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
  th { background: #f8f8f8; text-align: left; padding: 8px 10px;
       border-bottom: 2px solid #e5e5e5; white-space: nowrap; }
  td { padding: 6px 10px; border-bottom: 1px solid #f0f0f0; }
  tr:hover td { background: #fafafa; }

  /* Download link */
  .download-bar {
    margin-bottom: 24px;
  }
  .download-bar a {
    display: inline-block; background: #16a34a; color: #fff;
    text-decoration: none; border-radius: 6px; padding: 10px 24px;
    font-size: 0.9rem;
  }
  .download-bar a:hover { background: #15803d; }
</style>
</head>
<body>
<div class="container">

  <h1>Ianseo PDF to CSV Converter</h1>
  <p class="subtitle">Upload an Ianseo qualification protocol PDF to preview and convert.</p>

  <div class="upload-card">
    <form action="/convert" method="post" enctype="multipart/form-data">
      <input type="file" name="pdf" accept=".pdf" required>
      <button type="submit">Parse &amp; Preview</button>
    </form>
  </div>

  {% if result %}

  <!-- Stats -->
  <div class="stats">
    <div class="stat">
      <div class="label">File</div>
      <div class="value">{{ result.filename }}</div>
    </div>
    <div class="stat">
      <div class="label">Athletes</div>
      <div class="value">{{ result.athlete_count }}</div>
    </div>
    <div class="stat">
      <div class="label">Total Rows</div>
      <div class="value">{{ result.total_rows }}</div>
    </div>
    <div class="stat">
      <div class="label">Problems</div>
      <div class="value {{ 'bad' if result.problems else 'ok' }}">
        {{ result.problems | length }}
      </div>
    </div>
  </div>

  <!-- Problems / Warnings -->
  <div class="problems {{ 'has-problems' if result.problems else 'all-clear' }}">
    <h2>{% if result.problems %}Problems &amp; Warnings{% else %}No Problems Detected{% endif %}</h2>
    {% if result.problems %}
    <ul class="problem-list">
      {% for msg in result.problems %}
      <li>{{ msg }}</li>
      {% endfor %}
    </ul>
    {% else %}
    <p style="color:#16a34a; font-size:0.9rem;">All rows parsed and verified successfully.</p>
    {% endif %}
  </div>

  <!-- Download -->
  <div class="download-bar">
    <a href="/download">Download Full CSV ({{ result.total_rows }} rows)</a>
  </div>

  <!-- Data Preview Table -->
  <div class="table-card">
    <h2>Preview — first {{ result.preview_rows | length }} rows</h2>
    <table>
      <thead>
        <tr>
          <th>#</th>
          {% for col in result.columns %}
          <th>{{ col }}</th>
          {% endfor %}
        </tr>
      </thead>
      <tbody>
        {% for row in result.preview_rows %}
        <tr>
          <td>{{ loop.index }}</td>
          {% for val in row %}
          <td>{{ val }}</td>
          {% endfor %}
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  {% endif %}

</div>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Logging handler that captures warnings into a list
# ---------------------------------------------------------------------------

class _ListHandler(logging.Handler):
    """Collects WARNING+ log records into a plain list of strings."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord):
        self.messages.append(self.format(record))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template_string(_PAGE, result=None)


@app.route("/health")
def health():
    return {"status": "ok"}


@app.route("/convert", methods=["POST"])
def convert():
    if "pdf" not in request.files:
        return render_template_string(_PAGE, result=None), 400

    pdf_file = request.files["pdf"]
    if not pdf_file.filename or not pdf_file.filename.lower().endswith(".pdf"):
        return render_template_string(_PAGE, result=None), 400

    # Attach a handler to capture all warnings from the pipeline.
    capture = _ListHandler()
    capture.setFormatter(logging.Formatter("%(message)s"))
    root_logger = logging.getLogger("archery_parser")
    root_logger.addHandler(capture)
    root_logger.setLevel(logging.WARNING)

    try:
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
                result = {
                    "filename": pdf_file.filename,
                    "athlete_count": 0,
                    "total_rows": 0,
                    "problems": [f"FATAL: {exc}"],
                    "columns": [],
                    "preview_rows": [],
                }
                return render_template_string(_PAGE, result=result), 400

            if not rows:
                result = {
                    "filename": pdf_file.filename,
                    "athlete_count": len(records),
                    "total_rows": 0,
                    "problems": ["No CSV rows produced from this PDF."],
                    "columns": [],
                    "preview_rows": [],
                }
                return render_template_string(_PAGE, result=result)

            # Write CSV to temp file, then read bytes for download.
            csv_path = Path(tmpdir) / "output.csv"
            write_csv(rows, csv_path)
            csv_bytes = csv_path.read_bytes()

        # Store for download.
        output_name = Path(pdf_file.filename).stem + ".csv"
        _last_csv["name"] = output_name
        _last_csv["bytes"] = csv_bytes

        # Count unique athletes.
        athlete_names = {row.athlete for row in rows}

        # Build preview (first 20 rows).
        from archery_parser.models import CSVRow
        preview = [row.as_row() for row in rows[:20]]

        result = {
            "filename": pdf_file.filename,
            "athlete_count": len(athlete_names),
            "total_rows": len(rows),
            "problems": capture.messages,
            "columns": CSVRow.COLUMNS,
            "preview_rows": preview,
        }
        return render_template_string(_PAGE, result=result)

    finally:
        root_logger.removeHandler(capture)


@app.route("/download")
def download():
    if "bytes" not in _last_csv:
        return "No CSV available. Upload a PDF first.", 404
    return send_file(
        io.BytesIO(_last_csv["bytes"]),
        mimetype="text/csv",
        as_attachment=True,
        download_name=_last_csv.get("name", "output.csv"),
    )


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)
