import cv2
import json
import numpy as np
import sys
import os
from scipy.signal import savgol_filter


#trendshift_detection.py

# ================= CONFIG =================
SMOOTH_WINDOW = 31
# ==========================================


# ==========================================
# PURE TKINTER ROI SELECTOR
# No matplotlib. Works on every Windows/Mac/Linux Python install.
# ==========================================

def select_roi_tkinter(image_bgr):
    """
    Opens a resizable tkinter window.
    User clicks and drags to draw a rectangle.
    Returns (x, y, w, h) in ORIGINAL image pixel coordinates.
    """
    import tkinter as tk
    from PIL import Image, ImageTk   # pip install pillow

    orig_h, orig_w = image_bgr.shape[:2]

    # ── Fit image into screen (max 1200 × 700) ───────────────
    MAX_W, MAX_H = 1200, 700
    scale = min(MAX_W / orig_w, MAX_H / orig_h, 1.0)
    disp_w = int(orig_w * scale)
    disp_h = int(orig_h * scale)

    image_rgb  = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    pil_img    = Image.fromarray(image_rgb).resize((disp_w, disp_h), Image.LANCZOS)

    result = {"coords": None}   # filled on window close

    # ── Build window ──────────────────────────────────────────
    root = tk.Tk()
    root.title("ROI Selector  —  click and drag, then close")
    root.resizable(False, False)

    canvas = tk.Canvas(root, width=disp_w, height=disp_h, cursor="cross")
    canvas.pack()

    tk_img = ImageTk.PhotoImage(pil_img)
    canvas.create_image(0, 0, anchor=tk.NW, image=tk_img)

    info_var = tk.StringVar(value="LEFT-CLICK and DRAG to select the chart area")
    tk.Label(root, textvariable=info_var, fg="darkred",
             font=("Arial", 11, "bold")).pack(pady=4)

    state = {"x0": 0, "y0": 0, "rect_id": None, "drawing": False}

    def on_press(event):
        state["x0"] = event.x
        state["y0"] = event.y
        state["drawing"] = True
        if state["rect_id"]:
            canvas.delete(state["rect_id"])
        state["rect_id"] = canvas.create_rectangle(
            event.x, event.y, event.x, event.y,
            outline="red", width=2, dash=(4, 4)
        )

    def on_drag(event):
        if not state["drawing"]:
            return
        canvas.coords(state["rect_id"],
                      state["x0"], state["y0"],
                      event.x, event.y)
        # Live coordinate readout
        rx = int(min(state["x0"], event.x) / scale)
        ry = int(min(state["y0"], event.y) / scale)
        rw = int(abs(event.x - state["x0"]) / scale)
        rh = int(abs(event.y - state["y0"]) / scale)
        info_var.set(f"x={rx}  y={ry}  w={rw}  h={rh}  — release mouse, then close window")

    def on_release(event):
        if not state["drawing"]:
            return
        state["drawing"] = False
        # Convert display coords → original image coords
        x1 = int(min(state["x0"], event.x) / scale)
        y1 = int(min(state["y0"], event.y) / scale)
        x2 = int(max(state["x0"], event.x) / scale)
        y2 = int(max(state["y0"], event.y) / scale)
        # Clamp
        x1 = max(0, min(x1, orig_w - 1))
        y1 = max(0, min(y1, orig_h - 1))
        x2 = max(0, min(x2, orig_w))
        y2 = max(0, min(y2, orig_h))
        w  = x2 - x1
        h  = y2 - y1
        if w > 5 and h > 5:
            result["coords"] = (x1, y1, w, h)
            info_var.set(f"✅  Selected  x={x1}  y={y1}  w={w}  h={h}  — close window to continue")
        else:
            info_var.set("Too small — try again")

    canvas.bind("<ButtonPress-1>",   on_press)
    canvas.bind("<B1-Motion>",       on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)

    root.mainloop()

    if result["coords"] is None:
        print("[ROI] No selection — using full image.")
        return 0, 0, orig_w, orig_h

    print(f"[ROI] Confirmed: {result['coords']}")
    return result["coords"]


def select_roi_typed(image_bgr):
    """Fallback: save preview PNG and ask user to type coordinates."""
    h_img, w_img = image_bgr.shape[:2]
    preview = "roi_preview.png"
    cv2.imwrite(preview, image_bgr)
    print("\n" + "="*60)
    print(f"[ROI] GUI unavailable.")
    print(f"[ROI] Preview saved → {os.path.abspath(preview)}")
    print(f"[ROI] Image size: {w_img} × {h_img}")
    print("="*60)

    def ask(prompt, default, lo, hi):
        while True:
            try:
                raw = input(f"  {prompt} [default={default}]: ").strip()
                v = int(raw) if raw else default
                if lo <= v <= hi:
                    return v
                print(f"    Must be {lo}–{hi}.")
            except ValueError:
                print("    Enter a whole number.")

    x = ask(f"Start X  (0–{w_img-1})",  0,          0, w_img-1)
    y = ask(f"Start Y  (0–{h_img-1})",  0,          0, h_img-1)
    w = ask(f"Width    (1–{w_img-x})",  w_img - x,  1, w_img-x)
    h = ask(f"Height   (1–{h_img-y})",  h_img - y,  1, h_img-y)
    print(f"[ROI] Using: x={x}, y={y}, w={w}, h={h}\n")
    return x, y, w, h


def select_roi(image_bgr):
    """
    Tier 1 → tkinter drag-to-select  (needs Pillow: pip install pillow)
    Tier 2 → typed pixel coordinates  (always works)
    Tier 3 → full image               (silent last resort)
    """
    h, w = image_bgr.shape[:2]

    # ── Tier 1: tkinter ──────────────────────────────────────
    try:
        return select_roi_tkinter(image_bgr)
    except ImportError as e:
        missing = "Pillow" if "PIL" in str(e) else "tkinter"
        print(f"[ROI] {missing} not available → pip install pillow")
    except Exception as e:
        print(f"[ROI] tkinter selector failed: {e}")

    # ── Tier 2: typed ────────────────────────────────────────
    try:
        return select_roi_typed(image_bgr)
    except Exception as e:
        print(f"[ROI] Typed input failed: {e}. Using full image.")

    # ── Tier 3: full image ────────────────────────────────────
    return 0, 0, w, h


def show_result(image_bgr, save_path):
    """Display the final result in a tkinter window."""
    try:
        import tkinter as tk
        from PIL import Image, ImageTk

        orig_h, orig_w = image_bgr.shape[:2]
        MAX_W, MAX_H   = 1400, 800
        scale  = min(MAX_W / orig_w, MAX_H / orig_h, 1.0)
        disp_w = int(orig_w * scale)
        disp_h = int(orig_h * scale)

        rgb    = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        pil_img= Image.fromarray(rgb).resize((disp_w, disp_h), Image.LANCZOS)

        root   = tk.Tk()
        root.title(f"ZigZag Output  —  {save_path}")
        canvas = tk.Canvas(root, width=disp_w, height=disp_h)
        canvas.pack()
        tk_img = ImageTk.PhotoImage(pil_img)
        canvas.create_image(0, 0, anchor=tk.NW, image=tk_img)
        tk.Label(root, text="Close window to exit.",
                 font=("Arial", 10)).pack(pady=4)
        root.mainloop()

    except Exception:
        print(f"[Display] Open the result manually: {os.path.abspath(save_path)}")


# ==========================================
# MAIN CLASS  (logic unchanged)
# ==========================================

class RobustOriginalOverlay:
    def __init__(self, image_path):
        self.image_path       = image_path
        self.original_img     = None
        self.roi_coords       = None
        self.SENSITIVITY_PERCENT = 20

    def load_image(self):
        if not os.path.exists(self.image_path):
            print("Error: File not found.")
            sys.exit(1)
        self.original_img = cv2.imread(self.image_path)
        if self.original_img is None:
            print("Error: Could not decode image.")
            sys.exit(1)

    def select_roi(self):
        x, y, w, h = select_roi(self.original_img)
        self.roi_coords = (x, y, w, h)

    def get_clean_data(self):
        x_off, y_off, w, h = map(int, self.roi_coords)
        roi  = self.original_img[y_off:y_off+h, x_off:x_off+w]

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
        bg   = int(np.argmax(hist))
        diff = cv2.absdiff(gray, bg)
        _, mask = cv2.threshold(diff, 20, 255, cv2.THRESH_BINARY)

        h_k = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
        v_k = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40))
        grid = cv2.bitwise_or(cv2.morphologyEx(mask, cv2.MORPH_OPEN, h_k),
                               cv2.morphologyEx(mask, cv2.MORPH_OPEN, v_k))
        mask = cv2.bitwise_and(mask, cv2.bitwise_not(grid))

        k    = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)
        mask = cv2.dilate(mask, k, iterations=1)

        raw = []
        for x in range(w):
            ys = np.where(mask[:, x] > 0)[0]
            if len(ys) > 3:
                raw.append((x, int(np.median(ys))))
        if not raw:
            return []

        raw = np.array(raw)
        try:
            ys_s = (savgol_filter(raw[:, 1], SMOOTH_WINDOW, 3)
                    if len(raw) > SMOOTH_WINDOW else raw[:, 1])
            return [{'x': int(raw[i, 0]), 'high': int(ys_s[i]), 'low': int(ys_s[i])}
                    for i in range(len(raw))]
        except Exception as e:
            print(f"Smoothing failed: {e}")
            return [{'x': x, 'high': y, 'low': y} for x, y in raw]

    def calculate_zigzag(self, data):
        if not data:
            return []
        threshold_px = self.roi_coords[3] * (self.SENSITIVITY_PERCENT / 100.0)

        pivots = [{'x': data[0]['x'], 'y': data[0]['low'], 'type': 'low'}]
        look   = min(len(data)-1, 20)
        trend  = 1 if data[look]['high'] < data[0]['low'] else -1
        ch_y, ch_x = data[0]['high'], data[0]['x']
        cl_y, cl_x = data[0]['low'],  data[0]['x']

        for d in data:
            if trend == 1:
                if d['high'] < ch_y: ch_y, ch_x = d['high'], d['x']
                if d['low']  > ch_y + threshold_px:
                    pivots.append({'x': ch_x, 'y': ch_y, 'type': 'high'})
                    trend = -1; cl_y, cl_x = d['low'], d['x']
            else:
                if d['low']  > cl_y: cl_y, cl_x = d['low'], d['x']
                if d['high'] < cl_y - threshold_px:
                    pivots.append({'x': cl_x, 'y': cl_y, 'type': 'low'})
                    trend = 1;  ch_y, ch_x = d['high'], d['x']

        pivots.append({'x': data[-1]['x'], 'y': data[-1]['low'], 'type': 'low'})
        return pivots

    def draw_on_original(self, pivots):
        out     = self.original_img.copy()
        overlay = self.original_img.copy()
        ox, oy, _, _ = map(int, self.roi_coords)

        for i in range(len(pivots)-1):
            p1, p2    = pivots[i], pivots[i+1]
            up        = p2['y'] < p1['y']
            color     = (0, 200, 0) if up else (0, 0, 255)
            pt1       = (p1['x']+ox, p1['y']+oy)
            pt2       = (p2['x']+ox, p2['y']+oy)

            cv2.line(out, pt1, pt2, color, 1, cv2.LINE_AA)
            mx, my = (pt1[0]+pt2[0])//2, (pt1[1]+pt2[1])//2
            cv2.putText(out, "UPTREND" if up else "DOWNTREND",
                        (mx-30, my+(-25 if up else 25)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1, cv2.LINE_AA)
            if i > 0:
                cv2.circle(overlay, pt1, 35, (150, 220, 255), -1)
                cv2.putText(out, "TREND", (pt1[0]-18, pt1[1]-5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0,0,0), 1, cv2.LINE_AA)
                cv2.putText(out, "SHIFT", (pt1[0]-18, pt1[1]+8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0,0,0), 1, cv2.LINE_AA)

        cv2.addWeighted(overlay, 0.3, out, 0.7, 0, out)
        path = "zigzag_output_filtered.png"
        cv2.imwrite(path, out)
        print(f"✅ Saved → {path}")
        show_result(out, path)


# ==========================================
# ENTRY POINT
# ==========================================

if __name__ == "__main__":
    img_path = input("Enter path to chart image: ").strip().strip('"')
    app = RobustOriginalOverlay(img_path)
    app.load_image()
    app.select_roi()

    print("Pre-processing...")
    data = app.get_clean_data()

    if not data:
        print("❌ No valid data found in selection.")
    else:
        print(f"Calculating pivots (Sensitivity: {app.SENSITIVITY_PERCENT}%)...")
        pivots = app.calculate_zigzag(data)
        if len(pivots) > 1:
            app.draw_on_original(pivots)
        else:
            print("❌ No pivots found. Try lowering SENSITIVITY_PERCENT.")

# ==========================================
# PIPELINE-COMPATIBLE FUNCTION
# (Logic unchanged — only wires up I/O)
# ==========================================

def run_trendshift_logic(image_path, roi_coords, output_trend_json):
    """
    Pipeline entry point for trendshift detection.

    Params:
        image_path        — path to the original chart image
        roi_coords        — dict with crop_x, crop_y, crop_w, crop_h
        output_trend_json — where to write trend_data.json

    Returns:
        Path to trend_data.json, or None on failure.
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_trend_json)), exist_ok=True)

    app = RobustOriginalOverlay(image_path)
    app.load_image()

    # Inject ROI directly — no GUI prompt needed
    app.roi_coords = (
        roi_coords["crop_x"],
        roi_coords["crop_y"],
        roi_coords["crop_w"],
        roi_coords["crop_h"],
    )

    print("[TREND] Pre-processing image...")
    data = app.get_clean_data()

    if not data:
        print("[TREND] No valid data found in selection.")
        return None

    print(f"[TREND] Calculating pivots (Sensitivity: {app.SENSITIVITY_PERCENT}%)...")
    pivots = app.calculate_zigzag(data)

    if len(pivots) <= 1:
        print("[TREND] No pivots found.")
        return None

    return _save_trend_to_json(pivots, app.roi_coords, output_trend_json)


def _save_trend_to_json(pivots, roi_coords, output_path):
    """
    Convert zigzag pivots into structured JSON coordinate data.
    Saves trend lines, trend labels, and trend-shift markers.
    All coordinates are in ORIGINAL image space (roi offset applied).
    """
    ox, oy, _, _ = map(int, roi_coords)
    entries = []

    for i in range(len(pivots) - 1):
        p1, p2 = pivots[i], pivots[i + 1]
        up      = p2["y"] < p1["y"]
        pt1     = (p1["x"] + ox, p1["y"] + oy)
        pt2     = (p2["x"] + ox, p2["y"] + oy)
        mx      = (pt1[0] + pt2[0]) // 2
        my      = (pt1[1] + pt2[1]) // 2
        label_y = my - 25 if up else my + 25

        entries.append({
            "type":  "trend_line",
            "up":    up,
            "x1":    pt1[0], "y1": pt1[1],
            "x2":    pt2[0], "y2": pt2[1]
        })
        entries.append({
            "type": "trend_label",
            "text": "UPTREND" if up else "DOWNTREND",
            "x":    mx - 30,
            "y":    label_y
        })

        if i > 0:
            entries.append({
                "type": "trend_shift",
                "cx":   pt1[0],
                "cy":   pt1[1]
            })

    with open(output_path, "w") as f:
        json.dump(entries, f, indent=4)
    print(f"[TREND] Trend data saved -> {output_path}")
    return output_path


def _draw_to_path(app, pivots, output_path):
    """
    Legacy helper: draws zigzag output to an image file (standalone use).
    """
    import cv2
    import numpy as np

    out     = app.original_img.copy()
    overlay = app.original_img.copy()
    ox, oy, _, _ = map(int, app.roi_coords)

    for i in range(len(pivots) - 1):
        p1, p2 = pivots[i], pivots[i + 1]
        up    = p2["y"] < p1["y"]
        color = (0, 200, 0) if up else (0, 0, 255)
        pt1   = (p1["x"] + ox, p1["y"] + oy)
        pt2   = (p2["x"] + ox, p2["y"] + oy)

        cv2.line(out, pt1, pt2, color, 1, cv2.LINE_AA)
        mx, my = (pt1[0] + pt2[0]) // 2, (pt1[1] + pt2[1]) // 2
        cv2.putText(out, "UPTREND" if up else "DOWNTREND",
                    (mx - 30, my + (-25 if up else 25)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1, cv2.LINE_AA)

        if i > 0:
            cv2.circle(overlay, pt1, 35, (150, 220, 255), -1)
            cv2.putText(out, "TREND", (pt1[0] - 18, pt1[1] - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 0), 1, cv2.LINE_AA)
            cv2.putText(out, "SHIFT", (pt1[0] - 18, pt1[1] + 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 0), 1, cv2.LINE_AA)

    cv2.addWeighted(overlay, 0.3, out, 0.7, 0, out)
    cv2.imwrite(output_path, out)
    print(f"[TREND] Saved -> {output_path}")

