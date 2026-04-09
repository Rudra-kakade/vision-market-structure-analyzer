#  Stock Market Chart Analyzer

A Python-based computer vision pipeline that automatically analyzes trading chart images to detect **Market Structure (HH/HL/LH/LL)**, **Support & Resistance zones**, and **ZigZag trend shifts** — directly from screenshots, no data feed required.

---

##  Project Structure

```
stock-market-analyzer/
│
├── pipeline.py                  #   Main controller — runs all 4 steps in sequence
│
├── roi.py                       # Step 1 — ROI (Region of Interest) selector & cropper
├── new_markings.py              # Step 2 — Market structure detector (HH / HL / LH / LL)
├── support_resistance.py        # Step 3 — Support & Resistance zone generator
├── trendshift_detection.py      # Step 4 — ZigZag trend-shift detector
│
├── scrap.py                     #  Optional: TradingView screenshot capture tool
│
├── pipeline_state.json          # Auto-generated: persists paths & ROI across steps
├── roi_data.json                # Auto-generated: stores last ROI crop coordinates
├── requirements.txt             # Python dependencies
│
├── data/
│   ├── original_images/         # Copies of the raw input chart images
│   └── cropped_images/          # ROI-cropped versions used for analysis
│
├── outputs/
│   ├── markings/                # Step 2 output: HH/HL/LH/LL annotated images + JSON
│   ├── zones/                   # Step 3 output: Support & Resistance zone images
│   └── trends/                  # Step 4 output: ZigZag trend-shift images
│
└── captured_charts/             # Screenshots saved by scrap.py
```

---

##  How It Works

The pipeline accepts a chart image (local file or TradingView screenshot) and runs four sequential analysis steps:

```
[Input Image]
      │
      ▼
┌─────────────┐
│  Step 1     │  roi.py              → Select chart area, save crop
│  ROI Crop   │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Step 2     │  new_markings.py     → Detect swing highs/lows, label HH/HL/LH/LL
│  Structure  │                        Save annotated image + pivot_data.json
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Step 3     │  support_resistance.py → Cluster pivots into S/R zones
│  S/R Zones  │                          Draw shaded rectangles on chart
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Step 4     │  trendshift_detection.py → ZigZag algorithm, label UPTREND/DOWNTREND
│  Trends     │                            Highlight trend-shift pivot points
└─────────────┘
       │
       ▼
[pipeline_state.json updated with all output paths]
```

All intermediate results are written to `pipeline_state.json` so each step always knows exactly where to find its inputs.

---

##  Installation

**1. Clone the repository**
```bash
git clone https://github.com/yourusername/stock-market-analyzer.git
cd stock-market-analyzer
```

**2. Install dependencies**
```bash
pip install -r requirements.txt
```

**Requirements:**
```
streamlit
streamlit-cropper
opencv-python-headless
numpy
scipy
Pillow
matplotlib
```

> **Note:** `pyautogui` and `tkinter` are also used by `scrap.py` (the screenshot capture tool). These are optional if you only use local image files.

---

##  Usage

### Run the Full Pipeline
```bash
python pipeline.py
```

You will be prompted to choose an input mode:

```
==================================================
  Stock Market Analysis Pipeline
==================================================
  1  →  Analyse chart from a local image path
  2  →  Capture chart from TradingView (screenshot tool)
```

**Mode 1** — Enter a path to any chart image (PNG, JPG).  
**Mode 2** — Opens TradingView in your browser and launches the `scrap.py` screenshot tool.

---

### Run Individual Modules

Each module can also be run standalone for testing:

```bash
# ROI selector only
python roi.py

# Market structure detection only
python new_markings.py

# Support & Resistance zones only
python support_resistance.py

# Trend shift detection only
python trendshift_detection.py

# TradingView screenshot capture only
python scrap.py
```

---

##  Module Reference

### `pipeline.py` — Pipeline Controller
Orchestrates all four steps. Loads and saves the state to `pipeline_state.json` after every step, so the pipeline can be inspected or resumed.

| Function | Description |
|---|---|
| `step1_roi()` | Calls `roi.run_roi_logic()` |
| `step2_markings()` | Calls `new_markings.run_markings_logic()` |
| `step3_zones()` | Calls `support_resistance.run_support_resistance_logic()` |
| `step4_trends()` | Calls `trendshift_detection.run_trendshift_logic()` |

Steps 3 and 4 are **non-fatal** — the pipeline continues even if they fail.

---

### `roi.py` — ROI Selector
Opens the chart image and lets the user draw a rectangular selection. Saves:
- A copy of the original image to `data/original_images/`
- The cropped region to `data/cropped_images/`
- Crop coordinates to `roi_data.json`

**Public API:**
```python
result = run_roi_logic(
    image_path="chart.png",
    original_dir="data/original_images",
    cropped_dir="data/cropped_images",
    roi_json_path="roi_data.json"
)
# Returns: { "original_image": str, "cropped_image": str, "roi": {x, y, w, h} }
```

---

### `new_markings.py` — Market Structure (HH / HL / LH / LL)
Processes the cropped image to extract price data and classify swing points.

**Pipeline:**
1. **Preprocessing** — converts to grayscale, detects background intensity, removes gridlines and noise using morphological operations
2. **Price Extraction** — scans each pixel column to extract high/low Y positions; filters outliers using clustering and median/std deviation
3. **Peak Detection** — uses `scipy.signal.find_peaks` on smoothed high/low series (Savitzky-Golay filter) to find swing candidates
4. **Confirmation** — a swing is only confirmed if price subsequently moves at least `CONFIRM_PX = 25` pixels away from the candidate
5. **Labeling** — confirmed swings are classified as HH, HL, LH, LL (or EH/EL for equal levels)

**Scale parameter (1–10):** Controls sensitivity. Higher values require wider, more prominent swings.

**Public API:**
```python
crop_rect, json_path, img_path = run_markings_logic(
    img_path="cropped_chart.png",
    scale=5,
    output_prefix="analyzed",
    manual_crop_rect=(x, y, w, h),   # optional; skips GUI if provided
    output_dir="outputs/markings"
)
```

**Output JSON format (`pivot_data.json`):**
```json
[
  {
    "id": 1,
    "swing_index": 1,
    "type": "High",
    "label": "HH",
    "x": 342,
    "y": 87,
    "val": -87.0,
    "confirmed": true,
    "confirm_direction": "DOWN",
    "confirm_distance_px": 31
  }
]
```

---

### `support_resistance.py` — S/R Zone Generator
Reads the pivot JSON from Step 2 and draws shaded Support & Resistance zones on the chart.

**Algorithm:**
1. Separates pivots into `High` and `Low` groups
2. Clusters nearby pivots (within `tolerance = crop_h × 0.02`)
3. Draws a shaded rectangle between the first and last pivot of each cluster, provided the cluster has **at least 3 touches**
4. Red zones = Resistance (from Highs), Green zones = Support (from Lows)

**Public API:**
```python
output_path = run_support_resistance_logic(
    img_path="markings/analyzed_chart.png",
    json_path="markings/analyzed_chart.json",
    crop_rect=(x, y, w, h),
    output_prefix="zones",
    draw_labels=False,
    output_dir="outputs/zones"
)
```

---

### `trendshift_detection.py` — ZigZag Trend Shift
Runs a ZigZag algorithm over the smoothed price data to identify trend-shift pivot points.

**Algorithm:**
1. **Preprocessing** — same background-removal and grid-stripping as Step 2
2. **Column scan** — extracts median Y position per pixel column
3. **Smoothing** — Savitzky-Golay filter (`SMOOTH_WINDOW = 31`)
4. **ZigZag** — iterates data maintaining a `trend` direction; flips when price reverses by `SENSITIVITY_PERCENT = 20%` of ROI height
5. **Drawing** — green lines for uptrends, red lines for downtrends; yellow circles mark trend-shift points

**Public API:**
```python
output_path = run_trendshift_logic(
    image_path="original_chart.png",
    roi_coords=(x, y, w, h),
    output_dir="outputs/trends"
)
```

**Tunable constants (in `trendshift_detection.py`):**

| Constant | Default | Effect |
|---|---|---|
| `SMOOTH_WINDOW` | `31` | Smoothing window width; increase to reduce noise |
| `SENSITIVITY_PERCENT` | `20` | % of ROI height required for a trend flip; decrease to detect more swings |

---

### `scrap.py` — TradingView Screenshot Tool
A standalone Tkinter GUI that opens TradingView in your browser and lets you draw a screen-region capture.

- Saved screenshots go to `captured_charts/` with timestamped filenames (`chart_001_2026-03-04_16-22-22.png`)
- The pipeline's Mode 2 calls `scrap.main()` and then picks the most recently modified file

---

##  Output Files

| File | Description |
|---|---|
| `pipeline_state.json` | Full run state: all input/output paths and ROI |
| `roi_data.json` | Raw crop coordinates `{crop_x, crop_y, crop_w, crop_h}` |
| `outputs/markings/analyzed_*.png` | Chart annotated with HH/HL/LH/LL labels |
| `outputs/markings/analyzed_*.json` | Pivot data in JSON format |
| `outputs/zones/zones_*.png` | Chart with S/R zones drawn |
| `outputs/trends/zigzag_output_filtered.png` | Chart with ZigZag lines and trend-shift markers |

---

##  Technical Notes

### Image Preprocessing (shared across modules)
All modules use the same background-removal strategy:
1. Convert to grayscale
2. Find the dominant pixel intensity (background) via histogram
3. `absdiff` to isolate non-background pixels
4. Remove gridlines using horizontal/vertical morphological opening
5. Clean up noise with `MORPH_OPEN` + `MORPH_CLOSE`

### ROI Selector Tiers
Different modules use different GUI backends depending on availability:

| Module | Primary | Fallback |
|---|---|---|
| `roi.py` | `cv2.selectROI` | — |
| `new_markings.py` | `matplotlib RectangleSelector` | Full image |
| `trendshift_detection.py` | Tkinter drag-select | Typed coordinates → Full image |

When called through `pipeline.py`, all GUI selectors are bypassed — the ROI from Step 1 is injected directly into each module.

---

##  Requirements

- Python 3.9+
- OpenCV (`opencv-python-headless`)
- NumPy
- SciPy
- Pillow
- Matplotlib
- Tkinter (standard library, required for `scrap.py` and `trendshift_detection.py`)
- PyAutoGUI (required only for `scrap.py` screenshot capture)

---

## 📄 License

MIT License
