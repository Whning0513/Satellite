"""
animation.py
=============
O5: High-quality orbit animation with event labels, smooth zoom, and keyframes.
"""

import os, json, shutil, argparse, numpy as np
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.patches import Circle

from constants import GM_SUN, GM_EARTH, GM_MOON, AU_KM, R_MOON, R_MOON_SOI, DT_MAIN
from units import km_to_au
from nbody import GM_SEMR, vv_step_nbody
from trajectory import DesignParams, solve_trajectory
from horizons import fetch_sem_vectors, state_at_index


def smoothstep(t):
    return t*t*(3-2*t)


def _results_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "results"


def _load_json(name: str) -> dict:
    path = _results_dir() / name
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_animation_candidate() -> dict:
    for name, key in [
        ("m6_independent_window_search.json", "best_valid_candidate"),
        ("m6_complete_return_window_search.json", "best_valid_candidate"),
        ("m5_best_lunar_candidate_verify.json", "candidate"),
    ]:
        path = _results_dir() / name
        if path.exists():
            data = _load_json(name)
            candidate = data.get(key)
            if candidate:
                return candidate
    raise FileNotFoundError("no legal/formal candidate JSON available for animation")


def generate_trajectory(body_data, candidate, n_frames, dt_frame=DT_MAIN*2):
    """Propagate full 4-body trajectory, return state history + events."""
    t0_mjd = float(candidate["t0_mjd"])
    params = DesignParams(
        t0_mjd=t0_mjd,
        r_m=float(candidate["r_m_km"]),
        side=str(candidate["side"]),
        r_p=0.3*AU_KM,
    )
    result = solve_trajectory(params, body_data, verbose=False)

    r_s3, v_s3 = state_at_index(body_data, "Sun", 0)
    r_e0 = result.r_earth_t0; v_e0 = result.v_earth_t0
    r_m0 = result.r_moon_t0;  v_m0 = result.v_moon_t0
    vdir = -v_e0 / (np.linalg.norm(v_e0)+1e-15)
    r4 = [r_s3[:2], r_e0, r_m0, r_e0 + 7016*vdir]
    v4 = [v_s3[:2], v_e0, v_m0, v_e0 + result.v_inf_earth*vdir]

    total_s = max(result.t_total_days * 86400, 86400)
    n_steps_full = max(int(np.ceil(total_s / dt_frame)) + 1, n_frames)

    r_hist_full = [[ri.copy() for ri in r4]]
    t_hist_full = [0.0]

    for step in range(n_steps_full - 1):
        r4, v4 = vv_step_nbody(r4, v4, dt_frame, GM_SEMR, 4)
        r_hist_full.append([ri.copy() for ri in r4])
        t_hist_full.append((step + 1) * dt_frame)

    if len(r_hist_full) <= n_frames:
        r_hist = r_hist_full
        t_hist = t_hist_full
    else:
        sample_idx = np.linspace(0, len(r_hist_full) - 1, n_frames).round().astype(int)
        r_hist = [r_hist_full[i] for i in sample_idx]
        t_hist = [t_hist_full[i] for i in sample_idx]

    r_au = [[km_to_au(ri) for ri in state] for state in r_hist]

    event_days = {
        "launch": 0.0,
        "swingby": max(0.0, float(result.t_transfer_days)),
        "perihelion": max(0.0, float(result.t_transfer_days + 0.5 * result.t_coast_days)),
        "return": max(0.0, float(result.t_total_days)),
    }
    event_frames = {}
    for k, d in event_days.items():
        event_frames[k] = min(range(len(t_hist)), key=lambda i: abs(t_hist[i]/86400-d))

    traj_data = {"time_days": [float(t/86400) for t in t_hist],
                 "rocket_helio_AU": [[float(x) for x in s[3]] for s in r_au],
                 "events": {k: {"frame": int(v), "time_days": float(event_days[k])} for k, v in event_frames.items()},
                 "t0_mjd": t0_mjd,
                 "candidate": candidate}
    return r_au, t_hist, event_frames, result, traj_data


def save_keyframes(r_au, t_hist, event_frames, result, bd, out_dir, dpi=120):
    """Save 4 event keyframes + poster using pre-loaded body_data bd."""
    ex = km_to_au(np.array(bd["Earth"]["x_km"], dtype=float))
    ey = km_to_au(np.array(bd["Earth"]["y_km"], dtype=float))
    mx = km_to_au(np.array(bd["Moon"]["x_km"], dtype=float))
    my = km_to_au(np.array(bd["Moon"]["y_km"], dtype=float))
    rp_au = km_to_au(result.r_p_achieved_km)
    max_ext = max(1.2, rp_au*1.5)
    events = [("launch", "Launch"), ("swingby", "Swingby"),
              ("perihelion", "Perihelion"), ("return", "Return")]

    for key, title in events:
        frame = event_frames.get(key, 0)
        if frame >= len(r_au): continue
        s = r_au[frame]; _, r_e, r_m, r_r = s
        t_d = t_hist[frame]/86400
        hist = r_au[:frame+1]
        fig, ax = plt.subplots(figsize=(8, 6))
        ax.set_aspect("equal")
        ax.plot(ex, ey, "b--", lw=0.5, alpha=0.3)
        ax.plot(mx, my, "gray", lw=0.2, alpha=0.2)
        ax.plot([p[3][0] for p in hist], [p[3][1] for p in hist], "r-", lw=1.3, alpha=0.55)
        ax.scatter(0, 0, s=150, c="gold", ec="orange", zorder=5)
        ax.scatter(*r_e, c="blue", s=50, zorder=4)
        ax.scatter(*r_m, c="green", s=30, zorder=4)
        ax.scatter(*r_r, c="red", s=80, zorder=6)
        if key == "swingby":
            cx, cy = r_m[0], r_m[1]
            ax.set_xlim(cx-0.015, cx+0.015); ax.set_ylim(cy-0.015, cy+0.015)
            ax.add_patch(Circle((cx, cy), km_to_au(R_MOON_SOI),
                                fill=False, ec="gray", lw=0.5, ls="--", alpha=0.4))
        else:
            ax.set_xlim(-max_ext, max_ext); ax.set_ylim(-max_ext, max_ext)
        ax.set_xlabel("X (AU)"); ax.set_ylabel("Y (AU)"); ax.grid(alpha=0.3)
        ax.set_title(f"{title} (Day {t_d:.1f})", fontsize=12)
        fig.tight_layout()
        plt.savefig(out_dir/f"animation_keyframe_{key}.png", dpi=dpi, bbox_inches="tight")
        plt.close(fig)

    # Poster
    fig, ax = plt.subplots(figsize=(10, 8))
    ax.set_aspect("equal"); ax.set_xlim(-max_ext, max_ext); ax.set_ylim(-max_ext, max_ext)
    ax.scatter(0, 0, s=200, c="gold", ec="orange", zorder=5)
    ax.plot(ex, ey, "b--", lw=0.5, alpha=0.3)
    xs = [s[3][0] for s in r_au]; ys = [s[3][1] for s in r_au]
    ax.plot(xs, ys, "r-", lw=1.5, alpha=0.7)
    ax.scatter(xs[0], ys[0], c="blue", s=80, zorder=6, marker="o")
    ax.scatter(xs[-1], ys[-1], c="purple", s=80, zorder=6, marker="s")
    ax.set_xlabel("X (AU)"); ax.set_ylabel("Y (AU)"); ax.grid(alpha=0.3)
    ax.set_title("Orbit Trajectory", fontsize=12)
    fig.tight_layout()
    plt.savefig(out_dir/"animation_poster.png", dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    print("  [Anim] Keyframes + poster saved")


def generate_orbit_animation(t0_mjd=None, duration=30, fps=12, dpi=110):
    """Propagate → keyframes → render animation (single entry)."""
    bd = fetch_sem_vectors(use_cache=True)
    n_frames = int(duration * fps)
    candidate = _load_animation_candidate()
    if t0_mjd is not None:
        candidate = dict(candidate)
        candidate["t0_mjd"] = float(t0_mjd)
    r_au, t_hist, ev_f, result, traj_data = generate_trajectory(bd, candidate, n_frames)
    n_act = min(len(r_au), n_frames)
    r_au = r_au[:n_act]; t_hist = t_hist[:n_act]
    rp_au = km_to_au(result.r_p_achieved_km)
    dur_days = t_hist[-1]/86400 if t_hist else 96

    repo_root = Path(__file__).resolve().parents[1]
    out_dir = repo_root / "data" / "results"; out_dir.mkdir(parents=True, exist_ok=True)

    with open(out_dir/"animation_trajectory.json", "w", encoding="utf-8") as f:
        json.dump(traj_data, f, indent=2)

    save_keyframes(r_au, t_hist, ev_f, result, bd, out_dir, dpi)

    # ---- Set up animation figure ----
    fig, ax = plt.subplots(figsize=(10, 8))
    ax.set_aspect("equal")
    max_ext = max(1.2, rp_au*1.5)
    ax.set_xlim(-max_ext, max_ext)
    ax.set_ylim(-max_ext, max_ext)
    ax.set_xlabel("X (AU)"); ax.set_ylabel("Y (AU)"); ax.grid(alpha=0.2)
    ax.set_title("Earth → Moon Swingby → Perihelion → Earth (Legal Formal Candidate)", fontsize=12)

    ex = km_to_au(np.array(bd["Earth"]["x_km"], dtype=float))
    ey = km_to_au(np.array(bd["Earth"]["y_km"], dtype=float))
    mx = km_to_au(np.array(bd["Moon"]["x_km"], dtype=float))
    my = km_to_au(np.array(bd["Moon"]["y_km"], dtype=float))
    ax.plot(ex, ey, "b--", lw=0.5, alpha=0.25)
    ax.plot(mx, my, "gray", lw=0.2, alpha=0.15)
    ax.scatter(0, 0, s=200, c="gold", ec="orange", zorder=10, label="Sun")

    edot, = ax.plot([], [], "bo", ms=7, zorder=8, label="Earth")
    mdot, = ax.plot([], [], "go", ms=5, zorder=8, label="Moon")
    rdot, = ax.plot([], [], "ro", ms=6, zorder=9, label="Rocket")
    trail, = ax.plot([], [], "r-", lw=1.5, alpha=0.4, zorder=5)
    ax.legend(fontsize=7, loc="lower left")

    info = ax.text(0.02, 0.98, "", transform=ax.transAxes, fontsize=9,
                   va="top", bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.85))
    evlabel = ax.text(0.5, 0.92, "", transform=ax.transAxes, fontsize=14,
                      fontweight="bold", color="darkred", ha="center",
                      bbox=dict(boxstyle="round", facecolor="yellow", alpha=0.9))

    soi = Circle((0, 0), km_to_au(R_MOON_SOI), fill=False, ec="gray", lw=0.5, ls="--", alpha=0.0)
    ax.add_patch(soi)

    trail_len = min(150, n_act//3)
    events_seq = ["launch", "swingby", "perihelion", "return"]
    appeared = set()

    def init():
        edot.set_data([], []); mdot.set_data([], []); rdot.set_data([], [])
        trail.set_data([], []); info.set_text(""); evlabel.set_text("")
        soi.set_alpha(0.0)
        return edot, mdot, rdot, trail, info, evlabel, soi

    def animate(frame):
        s = r_au[frame]; r_s, r_e, r_m, r_r = s
        t_d = t_hist[frame]/86400
        edot.set_data([r_e[0]], [r_e[1]])
        mdot.set_data([r_m[0]], [r_m[1]])
        rdot.set_data([r_r[0]], [r_r[1]])
        st = max(0, frame-trail_len)
        tr = r_au[st:frame+1]
        trail.set_data([p[3][0] for p in tr], [p[3][1] for p in tr])

        ef_sb = ev_f.get("swingby", n_act//2)
        d_sb = abs(frame-ef_sb)/max(n_act//3, 1)
        t_sb = smoothstep(max(0, min(1, 1-d_sb/0.5)))
        z_zoom = 0.018
        z = z_zoom + (max_ext - z_zoom)*(1-t_sb)
        cx = r_m[0]*t_sb
        cy = r_m[1]*t_sb
        ax.set_xlim(cx-z, cx+z); ax.set_ylim(cy-z, cy+z)
        soi.center = (r_m[0], r_m[1])
        soi.set_alpha(0.4*max(0, 1-d_sb*1.5))

        info.set_text(f"Day {t_d:.1f}/{dur_days:.0f}\n"
                      f"R-Sun: {np.linalg.norm(r_r-r_s)*AU_KM/1e6:.2f}M km\n"
                      f"R-Moon: {np.linalg.norm(r_r-r_m)*AU_KM:.0f} km\n"
                      f"v_launch={result.v_launch:.2f} km/s\n"
                      f"r_p={candidate.get('perihelion_AU', rp_au):.4f} AU")

        for en in events_seq:
            ef = ev_f.get(en)
            if ef is None or en in appeared: continue
            if abs(frame-ef) < 6:
                appeared.add(en)
                lbl = {"launch":"LAUNCH","swingby":"SWINGBY","perihelion":"PERIHELION","return":"RETURN"}
                sub = {
                    "launch": f"MJD {candidate['t0_mjd']:.1f}",
                    "swingby": (
                        f"design r_m={candidate.get('r_m_km', result.params.r_m):.0f}km, "
                        f"sampled={result.dist_moon_min:.0f}km"
                    ),
                    "perihelion": f"formal r_p={candidate.get('perihelion_AU', rp_au):.4f} AU",
                    "return": (
                        f"return_vinf={candidate.get('return_vinf_kms', np.nan):.2f}km/s, "
                        f"dist={candidate.get('distance_to_earth_km', np.nan):.0f}km"
                    ),
                }
                evlabel.set_text(f"{lbl[en]}\n{sub[en]}")
                break
        return edot, mdot, rdot, trail, info, evlabel, soi

    print(f"  [Anim] Rendering {n_act} frames...")
    anim = animation.FuncAnimation(fig, animate, frames=n_act, init_func=init,
                                    blit=True, interval=1000/fps)

    build_dir = repo_root/"build"; build_dir.mkdir(parents=True, exist_ok=True)
    if shutil.which("ffmpeg"):
        # Detect available H.264 encoder: prefer h264_mf (Win) or open264
        import subprocess
        enc_test = subprocess.run(['ffmpeg', '-encoders'], capture_output=True, text=True)
        enc_info = enc_test.stdout + enc_test.stderr
        if 'libx264' in enc_info:
            codec = 'libx264'
        elif 'h264_mf' in enc_info:
            codec = 'h264_mf'
        elif 'libopenh264' in enc_info:
            codec = 'libopenh264'
        else:
            codec = 'mpeg4'
        path = build_dir/"orbit_animation.mp4"
        anim.save(str(path), writer=animation.FFMpegWriter(fps=fps, bitrate=4000, codec=codec), dpi=dpi)
        print(f"  [Anim] MP4 ({codec}) -> {path}")
    else:
        path = build_dir/"orbit_animation.gif"
        stale_mp4 = build_dir/"orbit_animation.mp4"
        if stale_mp4.exists():
            stale_mp4.unlink()
        anim.save(str(path), writer="pillow", fps=fps, dpi=dpi)
        print(f"  [Anim] GIF (no ffmpeg) -> {path}")
    print(f"[Anim] Done: {n_act} frames, {fps}fps, {duration}s")
    plt.close(fig)
    return str(path)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--duration", type=float, default=30)
    p.add_argument("--fps", type=int, default=12)
    p.add_argument("--dpi", type=int, default=110)
    a = p.parse_args()
    generate_orbit_animation(duration=a.duration, fps=a.fps, dpi=a.dpi)
