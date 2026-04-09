import cv2
import os
import json
import shutil

# ==========================================
# ROI SELECTOR — tkinter drag-to-select
# ==========================================

def select_roi_tkinter(image_bgr):
    """Opens a tkinter window for ROI selection. Returns (x, y, w, h)."""
    import tkinter as tk
    from PIL import Image, ImageTk

    orig_h, orig_w = image_bgr.shape[:2]
    MAX_W, MAX_H = 1200, 700
    scale  = min(MAX_W / orig_w, MAX_H / orig_h, 1.0)
    disp_w = int(orig_w * scale)
    disp_h = int(orig_h * scale)

    image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    from PIL import Image as PILImage
    pil_img   = PILImage.fromarray(image_rgb).resize((disp_w, disp_h), PILImage.LANCZOS)

    result = {"coords": None}

    root = tk.Tk()
    root.title("ROI Selector  —  click and drag to select chart area, then close")
    root.resizable(False, False)

    canvas = tk.Canvas(root, width=disp_w, height=disp_h, cursor="cross")
    canvas.pack()
    tk_img = ImageTk.PhotoImage(pil_img)
    canvas.create_image(0, 0, anchor=tk.NW, image=tk_img)

    info_var = tk.StringVar(value="LEFT-CLICK and DRAG to select the chart area, then close window")
    tk.Label(root, textvariable=info_var, fg="darkred",
             font=("Arial", 11, "bold")).pack(pady=4)

    state = {"x0": 0, "y0": 0, "rect_id": None, "drawing": False}

    def on_press(event):
        state["x0"], state["y0"] = event.x, event.y
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
        canvas.coords(state["rect_id"], state["x0"], state["y0"], event.x, event.y)
        rx = int(min(state["x0"], event.x) / scale)
        ry = int(min(state["y0"], event.y) / scale)
        rw = int(abs(event.x - state["x0"]) / scale)
        rh = int(abs(event.y - state["y0"]) / scale)
        info_var.set(f"x={rx}  y={ry}  w={rw}  h={rh}  — release mouse, then close window")

    def on_release(event):
        if not state["drawing"]:
            return
        state["drawing"] = False
        x1 = int(min(state["x0"], event.x) / scale)
        y1 = int(min(state["y0"], event.y) / scale)
        x2 = int(max(state["x0"], event.x) / scale)
        y2 = int(max(state["y0"], event.y) / scale)
        x1 = max(0, min(x1, orig_w - 1))
        y1 = max(0, min(y1, orig_h - 1))
        x2 = max(0, min(x2, orig_w))
        y2 = max(0, min(y2, orig_h))
        w, h = x2 - x1, y2 - y1
        if w > 5 and h > 5:
            result["coords"] = (x1, y1, w, h)
            info_var.set(f"Confirmed x={x1} y={y1} w={w} h={h}  — close window to continue")
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


# ==========================================
# PIPELINE-COMPATIBLE FUNCTION
# ==========================================

def run_roi_logic(image_path, original_images_dir, cropped_images_dir, roi_json_path):
    """
    Pipeline entry point for ROI selection.
    Returns dict: { original_image, cropped_image, roi: {crop_x, crop_y, crop_w, crop_h} }
    """
    image = cv2.imread(image_path)
    if image is None:
        raise FileNotFoundError(f"[ROI] Cannot load image: {image_path}")

    os.makedirs(original_images_dir, exist_ok=True)
    os.makedirs(cropped_images_dir,  exist_ok=True)

    filename = os.path.basename(image_path)
    original_save_path = os.path.join(original_images_dir, filename)
    shutil.copy(image_path, original_save_path)
    print(f"[ROI] Original image saved -> {original_save_path}")

    try:
        x, y, w, h = select_roi_tkinter(image)
    except Exception as e:
        print(f"[ROI] GUI selector failed ({e}), using full image.")
        h_img, w_img = image.shape[:2]
        x, y, w, h = 0, 0, w_img, h_img

    cropped = image[y:y + h, x:x + w]
    cropped_save_path = os.path.join(cropped_images_dir, "cropped_" + filename)
    cv2.imwrite(cropped_save_path, cropped)
    print(f"[ROI] Cropped image saved -> {cropped_save_path}")

    roi_data = {"crop_x": x, "crop_y": y, "crop_w": w, "crop_h": h}
    os.makedirs(os.path.dirname(roi_json_path) or ".", exist_ok=True)
    with open(roi_json_path, "w") as f:
        json.dump(roi_data, f, indent=4)
    print(f"[ROI] ROI data saved -> {roi_json_path}")

    return {
        "original_image": original_save_path,
        "cropped_image":  cropped_save_path,
        "roi":            roi_data,
    }


# ==========================================
# STANDALONE ENTRY POINT
# ==========================================

if __name__ == "__main__":
    image_path = input("Enter image path: ").strip()
    result = run_roi_logic(
        image_path,
        original_images_dir="original_images",
        cropped_images_dir="cropped_images",
        roi_json_path="roi_data.json",
    )
    print(f"Original : {result['original_image']}")
    print(f"Cropped  : {result['cropped_image']}")
    print(f"ROI      : {result['roi']}")
