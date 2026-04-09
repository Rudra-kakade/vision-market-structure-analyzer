"""
app.py — Flask bridge between chart_analysis_ui.html and pipeline.py
=====================================================================
Place this file in the SAME folder as pipeline.py, new_markings.py,
renderer.py, roi.py, support_resistance.py, trendshift_detection.py.

Install deps:
    pip install flask flask-cors

Run:
    python app.py

Then open:  http://localhost:5000
"""

import os
import json
import uuid
import threading
import traceback
from pathlib import Path
from datetime import datetime

from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS

# ──────────────────────────────────────────────────────────────────
# FLASK SETUP
# ──────────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder=".")
CORS(app)   # allow the HTML UI (any origin) to talk to this server

BASE_DIR    = Path(__file__).parent
UPLOAD_DIR  = BASE_DIR / "uploads"
OUTPUTS_DIR = BASE_DIR / "outputs"
DATA_DIR    = BASE_DIR / "data"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUTS_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

# In-memory job store  {job_id: {status, current_step, log_line, error, stats}}
jobs: dict[str, dict] = {}


# ──────────────────────────────────────────────────────────────────
# SERVE THE HTML UI
# ──────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    """Serve chart_analysis_ui.html from the same directory."""
    return send_from_directory(str(BASE_DIR), "chart_analysis_ui.html")


# ──────────────────────────────────────────────────────────────────
# STEP 1 — Upload image
# ──────────────────────────────────────────────────────────────────
@app.route("/upload", methods=["POST"])
def upload():
    """
    Receives a chart image from the UI via multipart/form-data.
    Saves it to uploads/ and returns the saved filename.

    UI calls:  POST /upload   (form field: 'file')
    Returns:   { "filename": "chart_xyz.png" }
    """
    if "file" not in request.files:
        return jsonify({"error": "No file field in request"}), 400

    f = request.files["file"]
    if f.filename == "":
        return jsonify({"error": "Empty filename"}), 400

    # Prefix with timestamp to avoid collisions
    stem, ext = os.path.splitext(f.filename)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = f"{stem}_{ts}{ext}"

    save_path = UPLOAD_DIR / safe_name
    f.save(str(save_path))
    print(f"[UPLOAD] Saved → {save_path}")

    return jsonify({"filename": safe_name, "path": str(save_path)})


# ──────────────────────────────────────────────────────────────────
# STEP 2–5 — Run full pipeline (async)
# ──────────────────────────────────────────────────────────────────
@app.route("/run", methods=["POST"])
def run():
    """
    Starts the full analysis pipeline in a background thread.
    The UI polls /status/<job_id> for progress.

    UI calls:  POST /run   { "filename": "...", "scale": 5 }
    Returns:   { "job_id": "uuid" }
    """
    data     = request.get_json(force=True)
    filename = data.get("filename")
    scale    = int(data.get("scale", 5))

    if not filename:
        return jsonify({"error": "filename is required"}), 400

    img_path = UPLOAD_DIR / filename
    if not img_path.exists():
        return jsonify({"error": f"File not found: {filename}"}), 404

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "status":       "running",
        "current_step": "roi",
        "log_line":     "",
        "error":        None,
        "stats":        {},
    }

    thread = threading.Thread(
        target=_run_pipeline_thread,
        args=(job_id, str(img_path), filename, scale),
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id})


def _run_pipeline_thread(job_id: str, img_path: str, filename: str, scale: int):
    """
    Runs pipeline.run_single_image() in a background thread and
    updates the jobs dict so the UI can poll for progress.

    Calls these modules (in order) via pipeline.py helpers:
        roi.py                  → step1_roi / make_full_roi
        new_markings.py         → step2_markings
        support_resistance.py   → step3_zones  (currently disabled)
        trendshift_detection.py → step4_trends
        renderer.py             → step5_render
    """
    try:
        # ── Import pipeline helpers ───────────────────────────────
        import sys
        sys.path.insert(0, str(BASE_DIR))
        from pipeline import (
            make_full_roi, step2_markings, step3_zones,
            step4_trends, step5_render, json_paths_for,
        )

        basename = os.path.basename(img_path)
        paths    = json_paths_for(basename)

        def _log(step_key, msg):
            jobs[job_id]["current_step"] = step_key
            jobs[job_id]["log_line"]     = msg
            print(f"[JOB {job_id}] [{step_key.upper()}] {msg}")

        # STEP 1 — ROI (no GUI in server mode — use full image)
        _log("roi", "Building full-image ROI (server mode — no GUI popup)")
        original_image, roi = make_full_roi(img_path, paths)

        # STEP 2 — Market structure
        _log("markings", f"Running new_markings.py  scale={scale}")
        step2_markings(original_image, roi, paths, scale)

        # STEP 3 — Zones (disabled per your pipeline; writes empty JSON)
        _log("zones", "Zone detection disabled — writing empty zones.json")
        step3_zones(original_image, roi, paths)

        # STEP 4 — Trend shifts
        _log("trend", "Running trendshift_detection.py")
        step4_trends(original_image, roi, paths)

        # STEP 5 — Render
        _log("render", "Running renderer.py")
        output_path = step5_render(original_image, paths)

        # ── Gather stats from JSON output ─────────────────────────
        stats = {}
        try:
            with open(paths["markings"]) as f:
                stats["pivots"] = len(json.load(f))
        except Exception:
            stats["pivots"] = 0
        try:
            with open(paths["zones"]) as f:
                stats["zones"] = len(json.load(f))
        except Exception:
            stats["zones"] = 0
        try:
            with open(paths["trend"]) as f:
                td = json.load(f)
                stats["trend"] = len([e for e in td if e.get("type") == "trend_line"])
        except Exception:
            stats["trend"] = 0

        jobs[job_id]["status"] = "done"
        jobs[job_id]["stats"]  = stats
        jobs[job_id]["current_step"] = "done"
        jobs[job_id]["log_line"] = f"Pipeline complete → {output_path}"

    except Exception as e:
        tb = traceback.format_exc()
        print(f"[JOB {job_id}] ERROR:\n{tb}")
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"]  = str(e)


# ──────────────────────────────────────────────────────────────────
# POLL STATUS
# ──────────────────────────────────────────────────────────────────
@app.route("/status/<job_id>")
def status(job_id: str):
    """
    UI polls this every 2 seconds while the pipeline runs.

    Returns: { status, current_step, log_line, error, stats }
    """
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Unknown job ID"}), 404
    return jsonify(job)


# ──────────────────────────────────────────────────────────────────
# SERVE OUTPUT IMAGE
# ──────────────────────────────────────────────────────────────────
@app.route("/result/<path:filename>")
def result(filename: str):
    """
    UI calls this to display the rendered chart image after completion.

    Example:  GET /result/chart_20250325_123456_analysis.png
    """
    full = OUTPUTS_DIR / filename
    if not full.exists():
        return jsonify({"error": f"Output not found: {filename}"}), 404
    return send_file(str(full), mimetype="image/png")


# ──────────────────────────────────────────────────────────────────
# BATCH MODE  (Mode 2 — TradingView screenshot capture)
# ──────────────────────────────────────────────────────────────────
@app.route("/run-batch", methods=["POST"])
def run_batch():
    """
    Launches scrap.py and then batch-processes all screenshots.
    Runs in a background thread so the UI doesn't time out.

    UI calls:  POST /run-batch  { "scale": 5 }
    Returns:   { "job_id": "uuid" }
    """
    data  = request.get_json(force=True) or {}
    scale = int(data.get("scale", 5))

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "status": "running",
        "current_step": "batch",
        "log_line": "Launching batch capture...",
        "error": None,
        "stats": {},
    }

    thread = threading.Thread(
        target=_run_batch_thread,
        args=(job_id, scale),
        daemon=True,
    )
    thread.start()
    return jsonify({"job_id": job_id})


def _run_batch_thread(job_id: str, scale: int):
    try:
        import sys
        sys.path.insert(0, str(BASE_DIR))
        from pipeline import run_batch_mode

        jobs[job_id]["log_line"] = "Running batch pipeline..."
        run_batch_mode(scale=scale)

        jobs[job_id]["status"]       = "done"
        jobs[job_id]["current_step"] = "done"
        jobs[job_id]["log_line"]     = "Batch processing complete"
    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"]  = str(e)


# ──────────────────────────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 55)
    print("  Chart Analysis API Server")
    print("=" * 55)
    print(f"  UI →  http://localhost:5000")
    print(f"  Base: {BASE_DIR}")
    print("=" * 55)
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
