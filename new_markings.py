import cv2
import numpy as np
import sys
import os
import json
from scipy.signal import find_peaks, savgol_filter

# ==========================================
# CONFIGURATION
# ==========================================
CONFIRM_PX = 25

# ==========================================
# MATPLOTLIB ROI SELECTOR
# (Replaces broken cv2.selectROI / cv2.imshow)
# ==========================================

def select_roi_matplotlib(image_bgr):
    """
    Opens a matplotlib window and lets the user draw a rectangle to select the
    chart ROI.  Returns (x, y, w, h) in pixel coordinates, or (0,0,W,H) if the
    user closes the window without drawing anything.

    Works on ANY system regardless of how OpenCV was compiled, because it relies
    on matplotlib (tkinter / Qt / Agg backend) instead of GTK/Cocoa/Win32.
    """
    import matplotlib
    import matplotlib.pyplot as plt
    import matplotlib.patches as patches
    from matplotlib.widgets import RectangleSelector

    # OpenCV stores images in BGR; matplotlib expects RGB
    image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    h_img, w_img = image_bgr.shape[:2]

    # We store the final selection here so the callback can write to it
    selection = {"x1": 0, "y1": 0, "x2": w_img, "y2": h_img, "made": False}

    fig, ax = plt.subplots(figsize=(14, 8))
    fig.canvas.manager.set_window_title(
        "Select Chart Area — click-drag a rectangle, then close this window"
    )
    ax.imshow(image_rgb)
    ax.set_title(
        "Click and drag to select the chart area, then close the window.",
        fontsize=10, color="navy"
    )

    def on_select(eclick, erelease):
        x1, y1 = int(min(eclick.xdata, erelease.xdata)), int(min(eclick.ydata, erelease.ydata))
        x2, y2 = int(max(eclick.xdata, erelease.xdata)), int(max(eclick.ydata, erelease.ydata))
        # Clamp to image bounds
        x1 = max(0, min(x1, w_img - 1))
        x2 = max(0, min(x2, w_img))
        y1 = max(0, min(y1, h_img - 1))
        y2 = max(0, min(y2, h_img))
        selection.update({"x1": x1, "y1": y1, "x2": x2, "y2": y2, "made": True})
        print(f"[ROI] Selected: x={x1}, y={y1}, w={x2-x1}, h={y2-y1}")

    rect_selector = RectangleSelector(
        ax, on_select,
        useblit=True,
        button=[1],              # left mouse button only
        minspanx=5, minspany=5,
        spancoords="pixels",
        interactive=True,
        props=dict(facecolor="yellow", edgecolor="red", alpha=0.25, fill=True),
    )

    print("[ROI] A window has opened.  Draw a rectangle over the chart, then close the window.")
    plt.tight_layout()
    plt.show()   # blocks until window is closed

    if not selection["made"]:
        print("[ROI] No selection made — using full image.")
        return 0, 0, w_img, h_img

    x, y = selection["x1"], selection["y1"]
    w, h = selection["x2"] - x, selection["y2"] - y
    return x, y, w, h


# ==========================================
# PREPROCESSOR
# ==========================================

class ChartPreprocessor:
    def __init__(self, image_path):
        self.image_path = image_path
        self.original_image = None
        self.cropped_image = None
        self.mask = None
        self.crop_x = 0
        self.crop_y = 0
        self.crop_w = 0
        self.crop_h = 0

    def load_image(self):
        self.original_image = cv2.imread(self.image_path)
        if self.original_image is None:
            raise ValueError(f"Could not load image from {self.image_path}")

    def set_manual_crop(self, x, y, w, h):
        if self.original_image is None:
            return
        self.crop_x, self.crop_y, self.crop_w, self.crop_h = x, y, w, h
        h_img, w_img = self.original_image.shape[:2]
        x, y = max(0, x), max(0, y)
        w, h = min(w, w_img - x), min(h, h_img - y)
        self.cropped_image = self.original_image[y:y+h, x:x+w]
        print(f"Applied previous crop: {x}, {y}, {w}, {h}")

    def select_roi(self):
        """
        Replaces the broken cv2.selectROI with the matplotlib-based picker.
        Falls back to full image automatically if matplotlib is unavailable
        or the user makes no selection.
        """
        if self.original_image is None:
            return

        try:
            x, y, w, h = select_roi_matplotlib(self.original_image)

            if w == 0 or h == 0:
                print("[ROI] Zero-size selection — using full image.")
                self.cropped_image = self.original_image.copy()
                self.crop_w = self.original_image.shape[1]
                self.crop_h = self.original_image.shape[0]
            else:
                self.crop_x, self.crop_y = x, y
                self.crop_w, self.crop_h = w, h
                self.cropped_image = self.original_image[y:y+h, x:x+w]
                print(f"[ROI] Image cropped to: x={x}, y={y}, w={w}, h={h}")

        except ImportError:
            print("[ROI] matplotlib not available — using full image.")
            self.cropped_image = self.original_image.copy()
            self.crop_w = self.original_image.shape[1]
            self.crop_h = self.original_image.shape[0]

        except Exception as e:
            print(f"[ROI] Selection error: {e} — using full image.")
            self.cropped_image = self.original_image.copy()
            self.crop_w = self.original_image.shape[1]
            self.crop_h = self.original_image.shape[0]

    def process_image(self):
        if self.cropped_image is None:
            self.cropped_image = self.original_image.copy()

        gray = cv2.cvtColor(self.cropped_image, cv2.COLOR_BGR2GRAY)

        hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
        background_intensity = int(np.argmax(hist))

        diff = cv2.absdiff(gray, background_intensity)
        _, self.mask = cv2.threshold(diff, 20, 255, cv2.THRESH_BINARY)

        horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
        detected_horizontal = cv2.morphologyEx(self.mask, cv2.MORPH_OPEN, horizontal_kernel)
        height, width = self.mask.shape
        vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, int(height * 0.5)))
        detected_vertical = cv2.morphologyEx(self.mask, cv2.MORPH_OPEN, vertical_kernel)
        grid_mask = cv2.bitwise_or(detected_horizontal, detected_vertical)
        self.mask = cv2.bitwise_and(self.mask, cv2.bitwise_not(grid_mask))

        kernel_clean = np.ones((3, 3), np.uint8)
        self.mask = cv2.morphologyEx(self.mask, cv2.MORPH_OPEN, kernel_clean)
        self.mask = cv2.morphologyEx(self.mask, cv2.MORPH_CLOSE, kernel_clean)
        return self.mask, self.cropped_image


# ==========================================
# ANALYZER
# ==========================================

class StockChartAnalyzer:
    def __init__(self, full_image, cropped_image, mask, crop_offset):
        self.full_image = full_image
        self.cropped_image = cropped_image
        self.candlestick_mask = mask
        self.crop_x, self.crop_y = crop_offset
        self.price_series = []
        self.pivots = []

    def extract_price_data(self):
        if self.candlestick_mask is None:
            return
        height, width = self.candlestick_mask.shape
        raw_data = []

        for x in range(width):
            column = self.candlestick_mask[:, x]
            pixels = np.where(column > 0)[0]
            if len(pixels) > 0:
                high_y, low_y = np.min(pixels), np.max(pixels)
                if (low_y - high_y) < 3:
                    continue
                if (low_y - high_y) < height * 0.9:
                    raw_data.append({'x': x, 'high_y': high_y, 'low_y': low_y})

        if not raw_data:
            return

        filtered_data = []
        x_set = set(p['x'] for p in raw_data)
        for p in raw_data:
            neighbors = sum(1 for offset in range(-5, 6) if (p['x'] + offset) in x_set)
            if neighbors >= 5:
                filtered_data.append(p)
        if not filtered_data:
            return

        clusters = []
        current_cluster = [filtered_data[0]]
        for i in range(1, len(filtered_data)):
            if filtered_data[i]['x'] - filtered_data[i-1]['x'] < 50:
                current_cluster.append(filtered_data[i])
            else:
                clusters.append(current_cluster)
                current_cluster = [filtered_data[i]]
        clusters.append(current_cluster)
        largest_cluster = max(clusters, key=len)

        y_values = [p['high_y'] for p in largest_cluster]
        median_y, std_dev = np.median(y_values), np.std(y_values)
        self.price_series = [
            p for p in largest_cluster
            if abs(p['high_y'] - median_y) < 4 * std_dev
        ]

    def analyze_structure(self, distance=20, prominence=10):
        if not self.price_series:
            return

        x_data = np.array([p['x'] for p in self.price_series])
        high_y_data = np.array([p['high_y'] for p in self.price_series])
        low_y_data = np.array([p['low_y'] for p in self.price_series])

        window_length = 15
        smooth_high = (savgol_filter(high_y_data, window_length, 3)
                       if len(high_y_data) > window_length else high_y_data)
        smooth_low = (savgol_filter(low_y_data, window_length, 3)
                      if len(low_y_data) > window_length else low_y_data)

        peaks,   _ = find_peaks(-smooth_high, distance=distance, prominence=prominence)
        troughs, _ = find_peaks(smooth_low,   distance=distance, prominence=prominence)

        candidates = []
        for i in peaks:
            candidates.append({
                'type': 'High', 'x': x_data[i],
                'y': int(high_y_data[i]), 'val': -high_y_data[i], 'data_idx': i
            })
        for i in troughs:
            candidates.append({
                'type': 'Low', 'x': x_data[i],
                'y': int(low_y_data[i]),  'val': -low_y_data[i],  'data_idx': i
            })
        candidates.sort(key=lambda k: k['x'])

        confirmed_swings = []
        last_confirmed_high = None
        last_confirmed_low  = None
        swing_counter = 1

        for cand in candidates:
            is_confirmed = False
            confirmation_dist = 0
            confirm_dir = ""

            for j in range(cand['data_idx'] + 1, len(self.price_series)):
                bar = self.price_series[j]
                if cand['type'] == 'High':
                    dist = bar['low_y'] - cand['y']
                    if dist >= CONFIRM_PX:
                        is_confirmed, confirmation_dist, confirm_dir = True, dist, "DOWN"
                        break
                else:
                    dist = cand['y'] - bar['high_y']
                    if dist >= CONFIRM_PX:
                        is_confirmed, confirmation_dist, confirm_dir = True, dist, "UP"
                        break

            if not is_confirmed:
                continue

            label = ""
            if cand['type'] == 'High':
                if last_confirmed_high is None:              label = "H"
                elif cand['val'] > last_confirmed_high['val']: label = "HH"
                elif cand['val'] < last_confirmed_high['val']: label = "LH"
                else:                                        label = "EH"
                last_confirmed_high = cand
            else:
                if last_confirmed_low is None:               label = "L"
                elif cand['val'] > last_confirmed_low['val']: label = "HL"
                elif cand['val'] < last_confirmed_low['val']: label = "LL"
                else:                                        label = "EL"
                last_confirmed_low = cand

            cand.update({
                'label': label, 'confirmed': True,
                'confirm_direction': confirm_dir,
                'confirm_distance_px': confirmation_dist,
                'swing_index': swing_counter
            })
            confirmed_swings.append(cand)
            swing_counter += 1

        self.pivots = confirmed_swings

    def visualize_results(self, output_path='output.png', draw_on_original=False):
        if self.full_image is None:
            return None
        result_img = self.full_image.copy() if draw_on_original else self.cropped_image.copy()
        offset_x = self.crop_x if draw_on_original else 0
        offset_y = self.crop_y if draw_on_original else 0

        for pivot in self.pivots:
            px = pivot['x'] + offset_x
            py = pivot['y'] + offset_y
            color = (0, 255, 0) if pivot['type'] == 'High' else (0, 0, 255)
            cv2.circle(result_img, (px, py), 3, color, -1)
            if 'label' in pivot:
                label_y = py - 10 if pivot['type'] == 'High' else py + 20
                cv2.putText(result_img, pivot['label'], (px - 10, label_y),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)

        cv2.imwrite(output_path, result_img)
        print(f"Image saved: {output_path}")
        return result_img

    def save_markings_to_json(self, output_path):
        data = []
        for i, pivot in enumerate(self.pivots):
            data.append({
                "id": i + 1,
                "swing_index": pivot.get('swing_index', 0),
                "type": pivot['type'],
                "label": pivot.get('label', ''),
                "x": int(pivot['x']),
                "y": int(pivot['y']),
                "val": float(pivot['val']),
                "confirmed": pivot.get('confirmed', False),
                "confirm_direction": pivot.get('confirm_direction', ''),
                "confirm_distance_px": int(pivot.get('confirm_distance_px', 0))
            })
        with open(output_path, 'w') as f:
            json.dump(data, f, indent=4)
        print(f"Data saved: {output_path}")


# ==========================================
# ENTRY POINT
# ==========================================

def run_markings_logic(img_path, scale, output_json_path,
                       manual_crop_rect=None):
    """
    Pipeline entry point for market structure detection.

    Params:
        img_path         — path to the original chart image
        scale            — analysis sensitivity 1-10
        output_json_path — where to write markings_data.json
        manual_crop_rect — (x, y, w, h) tuple; if None, opens GUI ROI selector

    Returns:
        (crop_rect tuple, json_path string)
        crop_rect = (crop_x, crop_y, crop_w, crop_h)
    """
    scale      = max(1, min(10, scale))
    distance   = 20 + (scale - 1) * 10
    prominence = 10 + (scale - 1) * 5

    preprocessor = ChartPreprocessor(img_path)
    preprocessor.load_image()

    if manual_crop_rect:
        preprocessor.set_manual_crop(*manual_crop_rect)
    else:
        preprocessor.select_roi()

    mask, cropped_image = preprocessor.process_image()
    crop_offset = (preprocessor.crop_x, preprocessor.crop_y)

    analyzer = StockChartAnalyzer(
        preprocessor.original_image, cropped_image, mask, crop_offset
    )
    analyzer.extract_price_data()
    analyzer.analyze_structure(distance=distance, prominence=prominence)

    os.makedirs(os.path.dirname(os.path.abspath(output_json_path)), exist_ok=True)
    analyzer.save_markings_to_json(output_json_path)

    crop_rect = (preprocessor.crop_x, preprocessor.crop_y,
                 preprocessor.crop_w, preprocessor.crop_h)
    return crop_rect, output_json_path


if __name__ == "__main__":
    path = (input("Image Path: ").strip().strip('"')
            if len(sys.argv) < 2 else sys.argv[1])
    if os.path.exists(path):
        try:
            s = int(input("Scale (1-10): "))
        except ValueError:
            s = 5
        run_markings_logic(path, s, "analyzed")
    else:
        print(f"[ERROR] File not found: {path}")