"""
interactive_demo.py
===================
O6: Tkinter interactive orbit demo — sliders for r_p, r_m, side, t0 offset.
Recomputes patched-conic + swingby in ~0.1s.

Usage:
  python src/interactive_demo.py             # GUI mode
  python src/interactive_demo.py --screenshot # headless screenshot
"""

import sys, os, argparse, math
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

import numpy as np
from constants import GM_SUN, GM_EARTH, GM_MOON, AU_KM, R_MOON, V_ESCAPE_EARTH, V_INF_MAX
from patched_conic import compute_patched_conic
from lunar_swingby import compute_swingby, compute_swingby_turn_angle
from units import rad_to_deg

# Try importing tkinter
try:
    import tkinter as tk
    from tkinter import ttk
    _HAVE_TK = True
except ImportError:
    _HAVE_TK = False

_HAVE_MPL = True
try:
    import matplotlib
    matplotlib.use("TkAgg" if _HAVE_TK else "Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
except ImportError:
    _HAVE_MPL = False


def compute_metrics(rp_AU, rm_km, side, t0_offset_days):
    """Quick patched-conic + swingby estimate."""
    elements = compute_patched_conic(r_p_AU=rp_AU)
    dv_launch = elements.v_launch
    v_inf = abs(elements.delta_v)

    # Simple swingby estimate (Moon at ~1 km/s)
    v_moon_est = 1.022
    v_inf_dir = math.pi/2 if t0_offset_days < 15 else -math.pi/2
    an = compute_swingby(rm_km, v_inf, v_inf_dir, np.array([0, v_moon_est]), side=side)

    v_rel_return = abs(elements.delta_v)
    dv_brake = max(0, v_rel_return - V_INF_MAX)
    dv_total = dv_launch + an.dv_mag + dv_brake

    t_total_days = elements.dt_flight_days + 5
    feasible = rm_km > R_MOON + 100 and v_rel_return < 30

    return {
        "dv_launch_kms": round(dv_launch, 2),
        "dv_lunar_kms": round(an.dv_mag, 3),
        "dv_reentry_brake_kms": round(dv_brake, 2),
        "dv_total_kms": round(dv_total, 2),
        "turn_angle_deg": round(an.delta_deg, 2),
        "v_inf_kms": round(v_inf, 2),
        "rp_achieved_AU": rp_AU,
        "t_total_days": round(t_total_days, 1),
        "feasible": feasible,
    }


class OrbitDemoApp:
    def __init__(self, master):
        self.master = master
        master.title("Orbit Design Demo (O6)")
        master.geometry("1000x700")

        # Sliders
        frame = ttk.Frame(master, padding=10)
        frame.grid(row=0, column=0, sticky="nsew")

        self.rp_var = tk.DoubleVar(value=0.3)
        self.rm_var = tk.DoubleVar(value=2237.4)
        self.side_var = tk.StringVar(value="trailing")
        self.t0_var = tk.DoubleVar(value=0)

        ttk.Label(frame, text="r_p (AU):").grid(row=0, column=0, sticky="w")
        self.rp_slider = ttk.Scale(frame, from_=0.05, to=0.8, variable=self.rp_var,
                                    orient="horizontal", command=self.on_update)
        self.rp_slider.grid(row=0, column=1, sticky="ew", padx=5)
        self.rp_label = ttk.Label(frame, text="0.30")
        self.rp_label.grid(row=0, column=2)

        ttk.Label(frame, text="r_m (km):").grid(row=1, column=0, sticky="w")
        self.rm_slider = ttk.Scale(frame, from_=1837.4, to=50000, variable=self.rm_var,
                                    orient="horizontal", command=self.on_update)
        self.rm_slider.grid(row=1, column=1, sticky="ew", padx=5)
        self.rm_label = ttk.Label(frame, text="2237")
        self.rm_label.grid(row=1, column=2)

        ttk.Label(frame, text="Side:").grid(row=2, column=0, sticky="w")
        side_frame = ttk.Frame(frame)
        side_frame.grid(row=2, column=1, sticky="w")
        ttk.Radiobutton(side_frame, text="Trailing", variable=self.side_var,
                        value="trailing", command=self.on_update).pack(side="left")
        ttk.Radiobutton(side_frame, text="Leading", variable=self.side_var,
                        value="leading", command=self.on_update).pack(side="left")

        ttk.Label(frame, text="t₀ offset (days):").grid(row=3, column=0, sticky="w")
        self.t0_slider = ttk.Scale(frame, from_=-15, to=15, variable=self.t0_var,
                                    orient="horizontal", command=self.on_update)
        self.t0_slider.grid(row=3, column=1, sticky="ew", padx=5)
        self.t0_label = ttk.Label(frame, text="0")
        self.t0_label.grid(row=3, column=2)

        # Buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=4, column=0, columnspan=3, pady=5)
        ttk.Button(btn_frame, text="Recompute", command=self.on_update).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Reset", command=self.reset).pack(side="left", padx=5)

        # Results display
        self.result_text = tk.Text(frame, height=8, width=50)
        self.result_text.grid(row=5, column=0, columnspan=3, pady=5)

        # Figure
        self.fig, self.ax = plt.subplots(figsize=(6, 4))
        self.canvas = FigureCanvasTkAgg(self.fig, master=master)
        self.canvas.get_tk_widget().grid(row=1, column=0, sticky="nsew")

        master.grid_rowconfigure(1, weight=1)
        master.grid_columnconfigure(0, weight=1)
        frame.grid_columnconfigure(1, weight=1)

        self.on_update()

    def on_update(self, *_):
        rp = self.rp_var.get()
        rm = self.rm_var.get()
        side = self.side_var.get()
        t0 = self.t0_var.get()

        self.rp_label.config(text=f"{rp:.3f}")
        self.rm_label.config(text=f"{rm:.0f}")
        self.t0_label.config(text=f"{t0:.0f}")

        m = compute_metrics(rp, rm, side, t0)
        self.result_text.delete(1.0, tk.END)
        self.result_text.insert(tk.END, f"dv_launch:     {m['dv_launch_kms']:>6.2f} km/s\n")
        self.result_text.insert(tk.END, f"dv_lunar:      {m['dv_lunar_kms']:>6.3f} km/s\n")
        self.result_text.insert(tk.END, f"dv_reentry:    {m['dv_reentry_brake_kms']:>6.2f} km/s\n")
        self.result_text.insert(tk.END, f"dv_total:      {m['dv_total_kms']:>6.2f} km/s\n")
        self.result_text.insert(tk.END, f"Turn angle:    {m['turn_angle_deg']:>6.1f}°\n")
        self.result_text.insert(tk.END, f"Flight time:   {m['t_total_days']:>6.1f} days\n")
        self.result_text.insert(tk.END, f"Feasible:      {str(m['feasible']):>6}\n")

        self.ax.clear()
        theta = np.linspace(0, 2*np.pi, 200)
        self.ax.plot(np.cos(theta), np.sin(theta), "b--", alpha=0.3, label="Earth orbit (1 AU)")
        rp_au = rp
        a = 0.5*(1+rp_au)
        e = 1 - rp_au/a
        th = np.linspace(0, np.pi, 100)
        r_orbit = a*(1-e**2)/(1+e*np.cos(th))
        self.ax.plot(r_orbit*np.cos(th), r_orbit*np.sin(th), "r-", lw=1.5, label="Transfer")
        self.ax.scatter(0, 0, s=100, c="gold", ec="orange", zorder=5, label="Sun")
        self.ax.scatter(-rp_au, 0, c="red", s=80, marker="*", zorder=6, label=f"Perihelion ({rp_au:.3f} AU)")
        self.ax.set_aspect("equal")
        self.ax.set_xlim(-1.2, 1.2); self.ax.set_ylim(-1.2, 1.2)
        self.ax.set_xlabel("X (AU)"); self.ax.set_ylabel("Y (AU)")
        self.ax.set_title(f"Orbit (r_p={rp_au:.3f} AU, {side}, t₀ offset={t0:.0f}d)")
        self.ax.grid(alpha=0.2); self.ax.legend(fontsize=7, loc="lower left")
        self.canvas.draw()

    def reset(self):
        self.rp_var.set(0.3)
        self.rm_var.set(2237.4)
        self.side_var.set("trailing")
        self.t0_var.set(0)
        self.on_update()


def save_screenshot():
    """Generate a static screenshot PNG without GUI."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    m = compute_metrics(0.3, 2237.4, "trailing", 0)
    fig, ax = plt.subplots(figsize=(8, 6))
    theta = np.linspace(0, 2*np.pi, 200)
    ax.plot(np.cos(theta), np.sin(theta), "b--", alpha=0.3)
    a = 0.5*(1+0.3); e = 1-0.3/a
    th = np.linspace(0, np.pi, 100)
    r_o = a*(1-e**2)/(1+e*np.cos(th))
    ax.plot(r_o*np.cos(th), r_o*np.sin(th), "r-", lw=1.5)
    ax.scatter(0, 0, s=100, c="gold", ec="orange", zorder=5)
    ax.scatter(-0.3, 0, c="red", s=80, marker="*", zorder=6)
    ax.set_aspect("equal"); ax.set_xlim(-1.2, 1.2); ax.set_ylim(-1.2, 1.2)
    ax.set_xlabel("X (AU)"); ax.set_ylabel("Y (AU)"); ax.grid(alpha=0.2)
    ax.set_title("Orbit Design Demo (O6)")

    # Metrics text box
    props = dict(boxstyle="round", facecolor="wheat", alpha=0.8)
    txt = "\n".join([f"{k}: {v}" for k, v in m.items()])
    ax.text(0.02, 0.98, txt, transform=ax.transAxes, fontsize=9,
            verticalalignment="top", bbox=props)

    out_dir = _REPO / "data" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "o6_interactive_screenshot.png"
    plt.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"[O6] Screenshot saved to {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshot", action="store_true", help="Generate screenshot without GUI")
    args = parser.parse_args()

    if args.screenshot:
        save_screenshot()
    elif _HAVE_TK and _HAVE_MPL:
        root = tk.Tk()
        app = OrbitDemoApp(root)
        root.mainloop()
    else:
        print("Tkinter not available. Use --screenshot flag for headless mode.")
        save_screenshot()
