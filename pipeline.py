"""
pipeline.py — Chart Analysis Pipeline Controller
=================================================
Full automated pipeline with two input modes:

  MODE 1 — Analyze a single chart image (with ROI selection)
  MODE 2 — Batch-process screenshots captured from TradingView

Pipeline steps:
  STEP 1  ROI selection      (roi.py)          [Mode 1 only]
  STEP 2  Market structure   (new_markings.py)  → markings_data.json
  STEP 3  Support/resistance (support_resistance.py) → zones_data.json
  STEP 4  Trend shift        (trendshift_detection.py) → trend_data.json
  STEP 5  Final render       (renderer.py)      → outputs/<name>_analysis.png

Mode 2 automatically skips charts that have already been analyzed.
"""

import os
import sys
import json
import glob
import time
import shutil
import traceback
from datetime import datetime

# ──────────────────────────────────────────────────────────────────
# PATHS & CONSTANTS
# ──────────────────────────────────────────────────────────────────
BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
DATA_DIR     = os.path.join(BASE_DIR, "data")
ORIGINAL_DIR = os.path.join(DATA_DIR, "original_images")
CROPPED_DIR  = os.path.join(DATA_DIR, "cropped_images")
OUTPUTS_DIR  = os.path.join(BASE_DIR, "outputs")
CAPTURED_DIR = os.path.join(BASE_DIR, "captured_charts")

for _d in [DATA_DIR, ORIGINAL_DIR, CROPPED_DIR, OUTPUTS_DIR, CAPTURED_DIR]:
    os.makedirs(_d, exist_ok=True)


# ──────────────────────────────────────────────────────────────────
# LOGGING
# ──────────────────────────────────────────────────────────────────

def log(tag, msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{tag}] {msg}")


def section(title):
    bar = "=" * 55
    print(f"\n{bar}\n  {title}\n{bar}")


# ──────────────────────────────────────────────────────────────────
# JSON PATHS FOR A GIVEN IMAGE (scoped per-image to support batch)
# ──────────────────────────────────────────────────────────────────

def json_paths_for(basename):
    """Return a dict of all per-image JSON and output paths."""
    stem = os.path.splitext(basename)[0]
    return {
        "roi":      os.path.join(DATA_DIR, f"{stem}_roi.json"),
        "markings": os.path.join(DATA_DIR, f"{stem}_markings.json"),
        "zones":    os.path.join(DATA_DIR, f"{stem}_zones.json"),
        "trend":    os.path.join(DATA_DIR, f"{stem}_trend.json"),
        "output":   os.path.join(OUTPUTS_DIR, f"{stem}_analysis.png"),
    }


# ──────────────────────────────────────────────────────────────────
# STEP 1 — ROI SELECTION  (Mode 1 only)
# ──────────────────────────────────────────────────────────────────

def step1_roi(image_path, paths):
    section("STEP 1 — ROI Selection")
    from roi import run_roi_logic

    result = run_roi_logic(
        image_path          = image_path,
        original_images_dir = ORIGINAL_DIR,
        cropped_images_dir  = CROPPED_DIR,
        roi_json_path       = paths["roi"],
    )
    log("STEP 1", f"ROI selected → {result['roi']}")
    return result["original_image"], result["roi"]


def make_full_roi(image_path, paths):
    """Build a full-image ROI (Mode 2 — no GUI)."""
    import cv2
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"Cannot load image: {image_path}")
    h, w = img.shape[:2]
    roi = {"crop_x": 0, "crop_y": 0, "crop_w": w, "crop_h": h}
    os.makedirs(os.path.dirname(os.path.abspath(paths["roi"])), exist_ok=True)
    with open(paths["roi"], "w") as f:
        json.dump(roi, f, indent=4)

    # Copy image to original_images so pipeline state is consistent
    dest = os.path.join(ORIGINAL_DIR, os.path.basename(image_path))
    if os.path.abspath(image_path) != os.path.abspath(dest):
        shutil.copy(image_path, dest)
    log("STEP 1", f"Full-image ROI set ({w}×{h}) → {paths['roi']}")
    return dest, roi


# ──────────────────────────────────────────────────────────────────
# STEP 2 — MARKET STRUCTURE DETECTION
# ──────────────────────────────────────────────────────────────────

def step2_markings(original_image, roi, paths, scale=5):
    section("STEP 2 — Market Structure Detection")
    from new_markings import run_markings_logic

    crop_rect = (roi["crop_x"], roi["crop_y"], roi["crop_w"], roi["crop_h"])
    _, json_path = run_markings_logic(
        img_path         = original_image,
        scale            = scale,
        output_json_path = paths["markings"],
        manual_crop_rect = crop_rect,
    )
    log("STEP 2", f"Market structure detected (scale={scale}) → {json_path}")
    return json_path


# ──────────────────────────────────────────────────────────────────
# STEP 3 — SUPPORT & RESISTANCE ZONES
# ──────────────────────────────────────────────────────────────────

def step3_zones(original_image, roi, paths):
    section("STEP 3 — Support & Resistance Zones (DISABLED)")
    # User requested to turn off zone section
    # Write an empty JSON so the renderer still has valid input
    os.makedirs(os.path.dirname(os.path.abspath(paths["zones"])), exist_ok=True)
    with open(paths["zones"], "w") as f:
        json.dump([], f)
    log("STEP 3", f"Zone detection disabled — empty zones passed to renderer.")
    return paths["zones"]


# ──────────────────────────────────────────────────────────────────
# STEP 4 — TREND SHIFT DETECTION
# ──────────────────────────────────────────────────────────────────

def step4_trends(original_image, roi, paths):
    section("STEP 4 — Trend Shift Detection")
    from trendshift_detection import run_trendshift_logic

    json_path = run_trendshift_logic(
        image_path        = original_image,
        roi_coords        = roi,
        output_trend_json = paths["trend"],
    )
    if json_path:
        log("STEP 4", f"Trend shifts detected → {json_path}")
    else:
        log("STEP 4", "No trend shifts detected — skipping trend layer.")
        # Write an empty JSON so renderer has something to load
        with open(paths["trend"], "w") as f:
            json.dump([], f)
    return paths["trend"]


# ──────────────────────────────────────────────────────────────────
# STEP 5 — FINAL RENDER
# ──────────────────────────────────────────────────────────────────

def step5_render(original_image, paths):
    section("STEP 5 — Rendering Final Chart")
    from renderer import render_chart

    output = render_chart(
        original_image_path = original_image,
        roi_json            = paths["roi"],
        markings_json       = paths["markings"],
        zones_json          = paths["zones"],
        trend_json          = paths["trend"],
        output_path         = paths["output"],
    )
    if output:
        log("STEP 5", f"Final chart saved → {output}")
    else:
        log("STEP 5", "Rendering failed.")
    return output


# ──────────────────────────────────────────────────────────────────
# FULL PIPELINE FOR ONE IMAGE
# ──────────────────────────────────────────────────────────────────

def run_single_image(image_path, use_roi_gui=True, scale=5):
    """
    Run the complete pipeline for one image.

    Params:
        image_path   — absolute path to the chart image
        use_roi_gui  — True = show ROI selector (Mode 1)
                       False = use full image as ROI (Mode 2)
        scale        — analysis sensitivity 1-10 (higher = more pivots detected)

    Returns:
        Path to the final analysis PNG, or None on failure.
    """
    basename = os.path.basename(image_path)
    paths    = json_paths_for(basename)

    log("INPUT", f"Chart loaded: {image_path}")
    errors = []

    # STEP 1
    try:
        if use_roi_gui:
            original_image, roi = step1_roi(image_path, paths)
        else:
            original_image, roi = make_full_roi(image_path, paths)
    except Exception as e:
        log("ERROR", f"Step 1 failed: {e}")
        traceback.print_exc()
        return None   # Cannot continue without ROI

    # STEP 2
    try:
        step2_markings(original_image, roi, paths, scale)
    except Exception as e:
        log("ERROR", f"Step 2 failed: {e}")
        traceback.print_exc()
        errors.append("Step 2 (markings)")

    # STEP 3
    try:
        step3_zones(original_image, roi, paths)
    except Exception as e:
        log("ERROR", f"Step 3 failed: {e}")
        traceback.print_exc()
        errors.append("Step 3 (zones)")
        # Write empty zones so renderer doesn't crash
        with open(paths["zones"], "w") as f:
            json.dump([], f)

    # STEP 4
    try:
        step4_trends(original_image, roi, paths)
    except Exception as e:
        log("ERROR", f"Step 4 failed: {e}")
        traceback.print_exc()
        errors.append("Step 4 (trends)")
        with open(paths["trend"], "w") as f:
            json.dump([], f)

    # STEP 5
    output = None
    try:
        output = step5_render(original_image, paths)
    except Exception as e:
        log("ERROR", f"Step 5 failed: {e}")
        traceback.print_exc()
        errors.append("Step 5 (render)")

    # Summary for this image
    section(f"Summary — {basename}")
    print(f"  Input      : {image_path}")
    print(f"  Markings   : {paths['markings']}")
    print(f"  Zones      : {paths['zones']}")
    print(f"  Trend      : {paths['trend']}")
    print(f"  Output     : {paths['output']}")
    if errors:
        print(f"\n  Warnings — steps with errors: {', '.join(errors)}")
    else:
        print("\n  All steps completed successfully.")

    return output


# ──────────────────────────────────────────────────────────────────
# MODE 2 — SCREENSHOT CAPTURE & BATCH PROCESSING
# ──────────────────────────────────────────────────────────────────

def launch_screenshot_capture():
    """Launch scrap.py and wait for the user to finish capturing."""
    import subprocess
    scrap_path = os.path.join(BASE_DIR, "scrap.py")
    log("CAPTURE", "Launching TradingView screenshot tool...")
    log("CAPTURE", "Capture your charts, then close the panel window to continue.")
    try:
        subprocess.run([sys.executable, scrap_path], check=True)
    except subprocess.CalledProcessError as e:
        log("CAPTURE", f"scrap.py exited with error: {e}")
    except FileNotFoundError:
        log("CAPTURE", "scrap.py not found — ensure it is in the same folder.")
        sys.exit(1)


def run_batch_mode(scale=5):
    """Launch capture tool, then analyze all new screenshots."""
    launch_screenshot_capture()
    time.sleep(0.5)

    screenshots = sorted(glob.glob(os.path.join(CAPTURED_DIR, "*.png")))
    if not screenshots:
        log("BATCH", "No screenshots found in captured_charts/. Exiting.")
        sys.exit(1)

    log("BATCH", f"Found {len(screenshots)} screenshot(s) in captured_charts/")

    processed, skipped, failed = [], [], []

    for img_path in screenshots:
        basename = os.path.basename(img_path)
        paths    = json_paths_for(basename)

        if os.path.exists(paths["output"]):
            log("BATCH", f"SKIP (already analyzed): {basename}")
            skipped.append(basename)
            continue

        log("BATCH", f"Processing: {basename}")
        result = run_single_image(img_path, use_roi_gui=False, scale=scale)
        if result:
            processed.append(basename)
        else:
            failed.append(basename)

    # Batch summary
    section("Batch Processing Summary")
    print(f"  Total screenshots : {len(screenshots)}")
    print(f"  Processed now     : {len(processed)}")
    print(f"  Skipped (done)    : {len(skipped)}")
    print(f"  Failed            : {len(failed)}")
    if failed:
        print(f"\n  Failed images: {', '.join(failed)}")


# ──────────────────────────────────────────────────────────────────
# MENU & ENTRY POINT
# ──────────────────────────────────────────────────────────────────

def choose_input_mode():
    print("\n" + "=" * 55)
    print("  Chart Analysis Pipeline")
    print("=" * 55)
    print("  1  ->  Analyze image from file path")
    print("  2  ->  Capture charts using TradingView screenshot tool")
    print("=" * 55)
    while True:
        choice = input("Choose mode [1/2]: ").strip()
        if choice in ("1", "2"):
            return int(choice)
        print("  Please enter 1 or 2.")


def ask_scale():
    """Prompt user for analysis scale (1-10). Returns int."""
    print()
    print("  Analysis Scale — controls sensitivity of pivot detection.")
    print("  Low (1-3)  = fewer, stronger pivots")
    print("  Mid (4-6)  = balanced  (default: 5)")
    print("  High (7-10)= many fine-grained pivots")
    while True:
        raw = input("  Enter scale [1-10, default=5]: ").strip()
        if raw == "":
            return 5
        try:
            val = int(raw)
            if 1 <= val <= 10:
                return val
            print("  Please enter a number between 1 and 10.")
        except ValueError:
            print("  Please enter a whole number.")


def run_pipeline():
    mode = choose_input_mode()
    scale = ask_scale()

    if mode == 2:
        run_batch_mode(scale=scale)

    else:  # mode == 1
        while True:
            path = input("\nEnter chart image path: ").strip().strip('"')
            if os.path.isfile(path):
                break
            print(f"  File not found: {path}")

        run_single_image(os.path.abspath(path), use_roi_gui=True, scale=scale)


if __name__ == "__main__":
    run_pipeline()
