"""
api.py — FastAPI Web Dashboard Backend
=======================================
Serves the frontend and orchestrates the chart analysis pipeline.

Endpoints:
  POST /upload-chart        → save uploaded image, return job_id
  POST /run-analysis        → start pipeline in background thread
  POST /capture-chart       → launch scrap.py TradingView capture
  GET  /logs/{job_id}       → SSE stream of real-time log lines
  GET  /result/{job_id}     → JSON {"url": "..."} when done
  GET  /outputs/{filename}  → serve final annotated PNG
  GET  /                    → serve index.html
"""

import io
import os
import sys
import json
import uuid
import time
import shutil
import threading
import traceback
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import (
    FileResponse, JSONResponse, StreamingResponse, HTMLResponse
)
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

# ─────────────────────────────────────────────────────────────────
# FAST API APP
# ─────────────────────────────────────────────────────────────────

app = FastAPI(title="Chart Analysis Dashboard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR  = os.path.join(BASE_DIR, "uploads")
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")
STATIC_DIR  = os.path.join(BASE_DIR, "static")

for _d in [UPLOAD_DIR, OUTPUTS_DIR, STATIC_DIR]:
    os.makedirs(_d, exist_ok=True)

# Serve static files (CSS, JS, etc.)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
# Serve output images
app.mount("/outputs", StaticFiles(directory=OUTPUTS_DIR), name="outputs")

# ─────────────────────────────────────────────────────────────────
# IN-MEMORY JOB STORE
# ─────────────────────────────────────────────────────────────────

jobs: dict[str, dict] = {}
# Schema per job:
# {
#   "status":   "pending" | "running" | "done" | "error",
#   "logs":     [str, ...],        # accumulated log lines
#   "image_path": str,             # abs path to uploaded image
#   "output_url": str | None,      # "/outputs/<filename>"
#   "scale":    int,
#   "lock":     threading.Lock()
# }


def _new_job(image_path: str, scale: int) -> str:
    jid = str(uuid.uuid4())
    jobs[jid] = {
        "status":     "pending",
        "logs":       [],
        "image_path": image_path,
        "output_url": None,
        "scale":      scale,
        "lock":       threading.Lock(),
    }
    return jid


def _append_log(jid: str, line: str):
    with jobs[jid]["lock"]:
        jobs[jid]["logs"].append(line)


# ─────────────────────────────────────────────────────────────────
# PIPELINE RUNNER  (executes in background thread)
# ─────────────────────────────────────────────────────────────────

class _PipelineLogger(io.StringIO):
    """Captures writes to stdout and appends them to the job log."""

    def __init__(self, jid: str):
        super().__init__()
        self._jid = jid
        self._buf  = ""

    def write(self, s: str):
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            line = line.strip()
            if line:
                _append_log(self._jid, line)

    def flush(self):
        pass


def _run_pipeline_thread(jid: str):
    job = jobs[jid]
    job["status"] = "running"

    # Redirect stdout so pipeline print() calls feed into log buffer
    old_stdout = sys.stdout
    sys.stdout  = _PipelineLogger(jid)

    try:
        # Import pipeline relative to this file's location
        if BASE_DIR not in sys.path:
            sys.path.insert(0, BASE_DIR)

        from pipeline import run_single_image  # noqa (local import intentional)

        _append_log(jid, "[API] Pipeline started…")
        output = run_single_image(
            image_path  = job["image_path"],
            use_roi_gui = False,        # web mode — no GUI
            scale       = job["scale"],
        )

        if output and os.path.exists(output):
            fname = os.path.basename(output)
            job["output_url"] = f"/outputs/{fname}"
            job["status"]     = "done"
            _append_log(jid, f"[API] ✅ Analysis complete → {fname}")
        else:
            job["status"] = "error"
            _append_log(jid, "[API] ❌ Pipeline returned no output.")

    except Exception:
        job["status"] = "error"
        tb = traceback.format_exc()
        for line in tb.splitlines():
            _append_log(jid, line)
        _append_log(jid, "[API] ❌ Pipeline crashed — see logs above.")

    finally:
        sys.stdout = old_stdout


# ─────────────────────────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = os.path.join(STATIC_DIR, "index.html")
    if not os.path.exists(html_path):
        raise HTTPException(status_code=404, detail="index.html not found")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()


@app.post("/upload-chart")
async def upload_chart(
    file:  UploadFile = File(...),
    scale: int        = Form(5),
):
    """Save uploaded chart image and create a job."""
    ext = os.path.splitext(file.filename)[-1].lower()
    if ext not in (".png", ".jpg", ".jpeg"):
        raise HTTPException(status_code=400, detail="Only PNG/JPG/JPEG allowed.")

    # Unique filename to avoid collisions
    unique_name = f"{uuid.uuid4().hex}{ext}"
    dest_path   = os.path.join(UPLOAD_DIR, unique_name)

    contents = await file.read()
    with open(dest_path, "wb") as f:
        f.write(contents)

    scale = max(1, min(10, scale))
    jid   = _new_job(dest_path, scale)
    _append_log(jid, f"[UPLOAD] File saved — {file.filename} ({len(contents):,} bytes)")

    return {"job_id": jid, "filename": file.filename, "scale": scale}


@app.post("/run-analysis")
async def run_analysis(body: dict):
    """Start the pipeline for an existing job_id."""
    jid = body.get("job_id")
    if not jid or jid not in jobs:
        raise HTTPException(status_code=404, detail="Job not found.")

    job = jobs[jid]
    if job["status"] == "running":
        return {"ok": True, "message": "Already running."}

    t = threading.Thread(target=_run_pipeline_thread, args=(jid,), daemon=True)
    t.start()

    return {"ok": True, "job_id": jid}


@app.get("/logs/{job_id}")
async def stream_logs(job_id: str):
    """SSE stream — pushes new log lines as they appear."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found.")

    def _event_generator():
        sent = 0
        while True:
            job = jobs[job_id]
            current_logs = list(job["logs"])   # snapshot
            new_lines = current_logs[sent:]
            for line in new_lines:
                yield f"data: {json.dumps({'line': line})}\n\n"
                sent += 1

            if job["status"] in ("done", "error") and sent >= len(job["logs"]):
                # Send a final control event so the client can stop listening
                yield f"data: {json.dumps({'status': job['status']})}\n\n"
                break

            time.sleep(0.25)

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/result/{job_id}")
async def get_result(job_id: str):
    """Return job status and output URL when pipeline is complete."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found.")

    job = jobs[job_id]
    return {
        "status":     job["status"],
        "output_url": job["output_url"],
    }


@app.post("/capture-chart")
async def capture_chart():
    """Launch the TradingView screenshot tool (scrap.py) as a subprocess."""
    import subprocess
    scrap_path = os.path.join(BASE_DIR, "scrap.py")
    if not os.path.exists(scrap_path):
        raise HTTPException(status_code=404, detail="scrap.py not found.")

    jid = str(uuid.uuid4())
    jobs[jid] = {
        "status":     "running",
        "logs":       ["[CAPTURE] Launching TradingView screenshot tool…"],
        "image_path": None,
        "output_url": None,
        "scale":      5,
        "lock":       threading.Lock(),
    }

    def _run_capture():
        try:
            result = subprocess.run(
                [sys.executable, scrap_path],
                capture_output=True, text=True
            )
            for line in result.stdout.splitlines():
                _append_log(jid, line)
            if result.returncode == 0:
                jobs[jid]["status"] = "done"
                _append_log(jid, "[CAPTURE] ✅ Capture session finished.")
            else:
                jobs[jid]["status"] = "error"
                _append_log(jid, f"[CAPTURE] ❌ scrap.py exited with code {result.returncode}")
        except Exception as e:
            jobs[jid]["status"] = "error"
            _append_log(jid, f"[CAPTURE] ❌ Error: {e}")

    threading.Thread(target=_run_capture, daemon=True).start()
    return {"job_id": jid}
