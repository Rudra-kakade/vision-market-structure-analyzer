"""
renderer.py — Final Chart Renderer
====================================
Loads the original chart image and all JSON coordinate data produced by
the analysis modules, then draws every layer in one final pass and saves
the annotated output image.

Drawing layers (in order):
  1. Support / resistance zones      (zones_data.json)
  2. Trend lines + UPTREND/DOWNTREND labels (trend_data.json)
  3. Trend-shift circles             (trend_data.json)
  4. Pivot circles + HH/HL/LH/LL labels     (markings_data.json)
"""

import cv2
import json
import os
import numpy as np


# ──────────────────────────────────────────────────────────────────
# LAYER DRAW HELPERS
# ──────────────────────────────────────────────────────────────────

def _draw_zones(image, overlay, zones):
    """Draw support (green) and resistance (red) zone rectangles."""
    for zone in zones:
        color = (0, 0, 255) if zone["type"] == "resistance" else (0, 255, 0)
        pt1 = (zone["x1"], zone["y1"])
        pt2 = (zone["x2"], zone["y2"])
        cv2.rectangle(overlay, pt1, pt2, color, -1)
        cv2.rectangle(image,   pt1, pt2, color,  1)


def _draw_trend_lines(image, overlay, trend_data):
    """Draw zigzag trend lines and UPTREND/DOWNTREND labels."""
    for entry in trend_data:
        if entry["type"] == "trend_line":
            up    = entry.get("up", True)
            color = (0, 200, 0) if up else (0, 0, 255)
            pt1   = (entry["x1"], entry["y1"])
            pt2   = (entry["x2"], entry["y2"])
            cv2.line(image, pt1, pt2, color, 1, cv2.LINE_AA)

        elif entry["type"] == "trend_label":
            up    = entry.get("up", True)
            color = (0, 200, 0) if "UP" in entry["text"] else (0, 0, 255)
            cv2.putText(
                image, entry["text"],
                (entry["x"], entry["y"]),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1, cv2.LINE_AA
            )

        elif entry["type"] == "trend_shift":
            cx, cy = entry["cx"], entry["cy"]
            cv2.circle(overlay, (cx, cy), 35, (150, 220, 255), -1)
            cv2.putText(image, "TREND", (cx - 18, cy - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 0), 1, cv2.LINE_AA)
            cv2.putText(image, "SHIFT", (cx - 18, cy + 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 0), 1, cv2.LINE_AA)


def _draw_pivots(image, markings, roi):
    """Draw pivot circles and HH/HL/LH/LL labels."""
    crop_x = roi.get("crop_x", 0)
    crop_y = roi.get("crop_y", 0)

    for pivot in markings:
        # Coordinates stored in markings are relative to the cropped image;
        # add the crop offset to map back to original image space.
        px = pivot["x"] + crop_x
        py = pivot["y"] + crop_y
        ptype = pivot.get("type", "High")
        label = pivot.get("label", "")

        color = (0, 255, 0) if ptype == "High" else (0, 0, 255)
        cv2.circle(image, (px, py), 4,  color, -1)
        cv2.circle(image, (px, py), 5,  (0, 0, 0), 1)

        if label:
            label_y = py - 15 if ptype == "High" else py + 25
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(image,
                          (px - 10, label_y - th - 1),
                          (px - 10 + tw, label_y + 3),
                          (255, 255, 255), -1)
            # Use darker green for better visibility on white background, else use red.
            text_color = (0, 200, 0) if ptype == "High" else (0, 0, 255)
            cv2.putText(image, label, (px - 10, label_y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, text_color, 1, cv2.LINE_AA)


# ──────────────────────────────────────────────────────────────────
# PUBLIC API
# ──────────────────────────────────────────────────────────────────

def render_chart(original_image_path,
                 roi_json,
                 markings_json,
                 zones_json,
                 trend_json,
                 output_path):
    """
    Draw all analysis layers onto the original chart image and save.

    Params:
        original_image_path — path to the unmodified chart image
        roi_json            — path to roi_data.json  (crop offset)
        markings_json       — path to markings_data.json
        zones_json          — path to zones_data.json
        trend_json          — path to trend_data.json
        output_path         — where to save the final annotated image

    Returns:
        output_path on success, None on failure.
    """
    # ── Load image ───────────────────────────────────────────────
    image = cv2.imread(original_image_path)
    if image is None:
        print(f"[RENDER] ERROR: Cannot load image: {original_image_path}")
        return None

    overlay = image.copy()

    # ── Load JSON data ───────────────────────────────────────────
    def _load(path, default):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"[RENDER] Warning — could not load {path}: {e}")
            return default

    roi      = _load(roi_json,      {"crop_x": 0, "crop_y": 0, "crop_w": 0, "crop_h": 0})
    markings = _load(markings_json, [])
    zones    = _load(zones_json,    [])
    trend    = _load(trend_json,    [])

    print(f"[RENDER] Loaded  {len(zones)} zones, "
          f"{len(markings)} pivots, "
          f"{len([e for e in trend if e['type']=='trend_line'])} trend segments")

    # ── Draw layers ──────────────────────────────────────────────
    # Order: zones (background) → trend lines → pivot labels (foreground)
    _draw_zones(image, overlay, zones)
    cv2.addWeighted(overlay, 0.35, image, 0.65, 0, image)   # semi-transparent zones

    overlay = image.copy()                                   # refresh overlay for shift circles
    _draw_trend_lines(image, overlay, trend)
    cv2.addWeighted(overlay, 0.3, image, 0.7, 0, image)     # semi-transparent shift circles

    _draw_pivots(image, markings, roi)

    # ── Save ─────────────────────────────────────────────────────
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    cv2.imwrite(output_path, image)
    print(f"[RENDER] Final chart saved -> {output_path}")
    return output_path


# ──────────────────────────────────────────────────────────────────
# STANDALONE ENTRY POINT
# ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 6:
        print("Usage: python renderer.py <image> <roi.json> <markings.json> <zones.json> <trend.json> [output.png]")
        sys.exit(1)

    img_p    = sys.argv[1]
    roi_p    = sys.argv[2]
    mark_p   = sys.argv[3]
    zones_p  = sys.argv[4]
    trend_p  = sys.argv[5]
    out_p    = sys.argv[6] if len(sys.argv) > 6 else "rendered_output.png"

    result = render_chart(img_p, roi_p, mark_p, zones_p, trend_p, out_p)
    if result:
        print(f"Done: {result}")
    else:
        print("Rendering failed.")
        sys.exit(1)
