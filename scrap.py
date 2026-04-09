import tkinter as tk
from tkinter import Canvas
import pyautogui
import os
from datetime import datetime
import webbrowser

# ---------------- CONFIG ---------------- #
SAVE_DIR = "captured_charts"
TRADINGVIEW_URL = "https://www.tradingview.com/chart/"
# ---------------------------------------- #

if not os.path.exists(SAVE_DIR):
    os.makedirs(SAVE_DIR)


def save_screenshot(region, count):
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename  = f"chart_{count:03d}_{timestamp}.png"
        filepath  = os.path.join(SAVE_DIR, filename)
        pyautogui.screenshot(region=region).save(filepath)
        print(f"✅ [{count}] Saved: {filepath}")
        return filepath
    except Exception as e:
        print(f"❌ Error: {e}")
        return None


class ControlPanel:
    PANEL_W = 280
    PANEL_H = 250

    def __init__(self):
        self.root             = tk.Tk()
        self.root.title("Chart Capture")
        self.screenshot_count = 0
        self._busy            = False
        self._coords          = None
        self._track_enabled   = True
        self._px              = 50
        self._py              = 50

        self.root.geometry(f"{self.PANEL_W}x{self.PANEL_H}+{self._px}+{self._py}")
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)
        self.root.bind("<Configure>", self._track_pos)

        bg, fg = "#2b2b2b", "#ffffff"
        self.root.configure(bg=bg)

        tk.Label(self.root, text="📊 Chart Capture",
                 font=("Arial", 16, "bold"), bg=bg, fg=fg).pack(pady=12)

        self.counter_lbl = tk.Label(self.root, text="Screenshots: 0",
                                    font=("Arial", 11), bg=bg, fg="#00ff00")
        self.counter_lbl.pack()

        self.status_lbl = tk.Label(self.root, text="Ready",
                                   font=("Arial", 9), bg=bg, fg="#aaaaaa")
        self.status_lbl.pack(pady=4)

        frm = tk.Frame(self.root, bg=bg)
        frm.pack(pady=8, padx=25, fill="both", expand=True)

        self.snap_btn = tk.Button(
            frm, text="📸  Screenshot",
            command=self._step1_hide,
            font=("Arial", 13, "bold"),
            bg="#0066cc", fg=fg, activebackground="#0052a3",
            relief="raised", bd=3, cursor="hand2"
        )
        self.snap_btn.pack(fill="x", pady=5, ipady=12)

        tk.Button(
            frm, text="❌  Quit",
            command=self.exit_app,
            font=("Arial", 12),
            bg="#cc0000", fg=fg, activebackground="#990000",
            relief="raised", bd=3, cursor="hand2"
        ).pack(fill="x", pady=5, ipady=10)

    def _track_pos(self, event):
        if self._track_enabled and event.widget == self.root:
            x, y = self.root.winfo_x(), self.root.winfo_y()
            sw   = self.root.winfo_screenwidth()
            sh   = self.root.winfo_screenheight()
            if 0 <= x < sw and 0 <= y < sh:
                self._px, self._py = x, y

    # ══════════════════════════════════════════════════════════════════
    # STEP 1 — save position, lock tracking, move off-screen
    # ══════════════════════════════════════════════════════════════════
    def _step1_hide(self):
        if self._busy:
            return
        self._busy = True
        self.snap_btn.config(state="disabled")
        self.status_lbl.config(text="Draw selection...", fg="#ffff00")

        # Lock in real position BEFORE moving
        self._px = self.root.winfo_x()
        self._py = self.root.winfo_y()
        self._track_enabled = False

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{self.PANEL_W}x{self.PANEL_H}+{sw + 500}+{sh + 500}")
        self.root.update()

        self.root.after(300, self._step2_snip)

    # ══════════════════════════════════════════════════════════════════
    # STEP 2 — open snipping overlay
    # ══════════════════════════════════════════════════════════════════
    def _step2_snip(self):
        self._coords = None

        snip = tk.Toplevel(self.root)
        snip.attributes("-fullscreen", True)
        snip.attributes("-alpha", 0.25)
        snip.attributes("-topmost", True)
        snip.config(cursor="cross")

        canvas = Canvas(snip, highlightthickness=0, bg="black")
        canvas.pack(fill="both", expand=True)

        state = {"x0": 0, "y0": 0, "rect": None}

        def on_press(e):
            state["x0"], state["y0"] = e.x, e.y
            state["rect"] = canvas.create_rectangle(
                e.x, e.y, e.x, e.y, outline="red", width=2
            )

        def on_drag(e):
            if state["rect"]:
                canvas.coords(state["rect"], state["x0"], state["y0"], e.x, e.y)

        def on_release(e):
            x1 = min(state["x0"], e.x);  y1 = min(state["y0"], e.y)
            x2 = max(state["x0"], e.x);  y2 = max(state["y0"], e.y)
            if (x2 - x1) > 5 and (y2 - y1) > 5:
                self._coords = (x1, y1, x2 - x1, y2 - y1)
            snip.destroy()

        canvas.bind("<ButtonPress-1>",   on_press)
        canvas.bind("<B1-Motion>",       on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        snip.bind("<Escape>",            lambda e: snip.destroy())

        # When snip closes → step 3 (panel still off-screen at this point)
        # Guard: <Destroy> fires for every child widget too — only act for snip itself
        snip.bind("<Destroy>", lambda e: self.root.after(50, self._step3_screenshot_first)
                  if e.widget is snip else None)


    # ══════════════════════════════════════════════════════════════════
    # STEP 3 — screenshot FIRST (panel still off-screen), THEN restore
    # ══════════════════════════════════════════════════════════════════
    def _step3_screenshot_first(self):
        # ✅ Panel is still off-screen here — take screenshot NOW
        if self._coords:
            self.screenshot_count += 1
            save_screenshot(self._coords, self.screenshot_count)

        # NOW bring panel back — it won't appear in the saved image
        self.root.geometry(f"{self.PANEL_W}x{self.PANEL_H}+{self._px}+{self._py}")
        self.root.update()
        self._track_enabled = True
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.focus_force()

        # Update UI
        if self._coords:
            self.counter_lbl.config(text=f"Screenshots: {self.screenshot_count}")
            self.status_lbl.config(text=f"✅  Saved #{self.screenshot_count}", fg="#00ff00")
        else:
            self.status_lbl.config(text="⚠️  Cancelled — try again", fg="#ff8800")

        self.snap_btn.config(state="normal")
        self._busy = False

    def exit_app(self):
        print(f"\n✅ Total captured: {self.screenshot_count}")
        print(f"📂 Saved in: {os.path.abspath(SAVE_DIR)}")
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    print("--- Chart Capture Tool ---")
    print(f"📂 Folder: {os.path.abspath(SAVE_DIR)}")
    webbrowser.open(TRADINGVIEW_URL)
    ControlPanel().run()


if __name__ == "__main__":
    main()