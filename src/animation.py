"""
animation.py
=============
O5: Orbit animation — full trajectory + keyframe PNGs.

Outputs:
  build/orbit_animation.mp4     (or .gif fallback)
  data/results/animation_keyframe_launch.png
  data/results/animation_keyframe_swingby.png
  data/results/animation_keyframe_perihelion.png
  data/results/animation_keyframe_return.png
"""

import os, numpy as np, shutil
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.animation as animation

from constants import GM_SUN, GM_EARTH, GM_MOON, AU_KM, R_MOON, R_MOON_SOI, DT_MAIN
from units import km_to_au
from nbody import GM_SEMR, vv_step_nbody
from trajectory import DesignParams, solve_trajectory
from horizons import fetch_sem_vectors, state_at_index


def propagate_full_trajectory(body_data, t0_mjd, dt_frame=DT_MAIN):
    """Propagate full trajectory, return position history + event times."""
    params = DesignParams(t0_mjd=t0_mjd, r_m=R_MOON+500, side="trailing", r_p=0.3*AU_KM)
    result = solve_trajectory(params, body_data, verbose=False)

    # Initial 4-body state
    r_sun3, v_sun3 = state_at_index(body_data, "Sun", 0)
    r_earth_t0, v_earth_t0 = result.r_earth_t0, result.v_earth_t0
    r_moon_t0, v_moon_t0 = result.r_moon_t0, result.v_moon_t0
    v_inf_dir = -v_earth_t0 / (np.linalg.norm(v_earth_t0) + 1e-15)
    r_rocket_t0 = r_earth_t0 + 7016.0 * v_inf_dir
    v_rocket_t0 = v_earth_t0 + result.v_inf_earth * v_inf_dir

    r4 = [r_sun3[:2], r_earth_t0, r_moon_t0, r_rocket_t0]
    v4 = [v_sun3[:2], v_earth_t0, v_moon_t0, v_rocket_t0]

    total_sec = max(result.t_total_days * 86400.0, 86400.0)
    n_steps = int(total_sec / dt_frame)

    r_hist, t_hist = [], []
    r_min_sun, rocket_closest_moon = np.inf, np.inf
    t_min_sun, t_closest_moon = 0.0, 0.0

    for step in range(n_steps):
        t_now = step * dt_frame
        r4, v4 = vv_step_nbody(r4, v4, dt_frame, GM_SEMR, 4)
        if step % max(n_steps // 500, 1) == 0:
            r_hist.append([ri.copy() for ri in r4])
            t_hist.append((step + 1) * dt_frame)

        moon_d = np.linalg.norm(r4[3] - r4[2])
        if moon_d < rocket_closest_moon:
            rocket_closest_moon = moon_d
            t_closest_moon = (step + 1) * dt_frame
        sun_d = np.linalg.norm(r4[3] - r4[0])
        if sun_d < r_min_sun:
            r_min_sun = sun_d
            t_min_sun = (step + 1) * dt_frame

    r_hist_au = [[km_to_au(ri) for ri in state] for state in r_hist]
    events = {
        "launch_day": 0.0,
        "swingby_day": t_closest_moon / 86400.0,
        "perihelion_day": t_min_sun / 86400.0,
        "return_day": result.t_total_days,
    }
    return r_hist_au, t_hist, events, result


def save_keyframe(body_data, r_state_au, t_sec, event_name, out_dir, dpi=120):
    """Save a single event keyframe."""
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.set_aspect("equal")
    r_p_AU = km_to_au(0.3 * AU_KM)
    max_ext = max(1.2, r_p_AU * 1.5)
    ax.set_xlim(-max_ext, max_ext)
    ax.set_ylim(-max_ext, max_ext)

    # Background orbits
    earth_x = km_to_au(np.array(body_data["Earth"]["x_km"], dtype=float))
    earth_y = km_to_au(np.array(body_data["Earth"]["y_km"], dtype=float))
    moon_x = km_to_au(np.array(body_data["Moon"]["x_km"], dtype=float))
    moon_y = km_to_au(np.array(body_data["Moon"]["y_km"], dtype=float))

    ax.plot(earth_x, earth_y, "b--", lw=0.5, alpha=0.3, label="Earth orbit")
    ax.plot(moon_x, moon_y, "gray", lw=0.2, alpha=0.2, label="Moon orbit")
    ax.scatter(0, 0, s=150, c="gold", edgecolors="orange", zorder=5, label="Sun")

    # Rocket position and trail
    r_s, r_e, r_m, r_r = r_state_au
    ax.scatter(*r_r, c="red", s=50, zorder=6, label="Rocket")
    ax.scatter(*r_e, c="blue", s=30, zorder=4, label="Earth")
    ax.scatter(*r_m, c="green", s=20, zorder=4, label="Moon")

    t_days = t_sec / 86400.0
    ax.set_title(f"{event_name} (Day {t_days:.1f})")
    ax.set_xlabel("X (AU)")
    ax.set_ylabel("Y (AU)")
    ax.legend(fontsize=7, loc="lower left")
    ax.grid(alpha=0.3)

    plt.savefig(out_dir / f"animation_keyframe_{event_name.lower().replace(' ','_')}.png",
                dpi=dpi, bbox_inches="tight")
    plt.close(fig)


def generate_orbit_animation(body_data=None, t0_mjd=61154.0,
                              filename="orbit_animation.mp4", fps=20,
                              duration_sec=40, dpi=120, dt_frame=DT_MAIN):
    """Generate orbit animation + keyframe PNGs."""
    if body_data is None:
        body_data = fetch_sem_vectors(use_cache=True)

    print("[Anim] Propagating full trajectory...")
    r_hist_au, t_hist, events, result = propagate_full_trajectory(body_data, t0_mjd, dt_frame)
    print(f"[Anim] {len(r_hist_au)} frames, r_p={km_to_au(result.r_p_achieved_km):.4f} AU")

    # Event indices
    event_times_sec = [events["launch_day"]*86400, events["swingby_day"]*86400,
                        events["perihelion_day"]*86400, events["return_day"]*86400]
    event_names = ["Launch", "Swingby", "Perihelion", "Return"]
    event_indices = [min(range(len(t_hist)), key=lambda i: abs(t_hist[i]-et)) for et in event_times_sec]

    # Save keyframes
    repo_root = Path(__file__).resolve().parents[1]
    out_dir = repo_root / "data" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)

    for idx, name in zip(event_indices, event_names):
        save_keyframe(body_data, r_hist_au[idx], t_hist[idx], name, out_dir, dpi)
        print(f"[Anim] Keyframe saved: {name}")

    # Build animation
    fig, ax = plt.subplots(figsize=(8, 8))
    ax.set_aspect("equal")
    r_p_AU = km_to_au(result.r_p_achieved_km)
    max_ext = max(1.2, r_p_AU * 1.5)
    ax.set_xlim(-max_ext, max_ext)
    ax.set_ylim(-max_ext, max_ext)
    ax.set_xlabel("X (AU)")
    ax.set_ylabel("Y (AU)")
    ax.set_title("Earth → Moon Swingby → Perihelion → Earth")
    ax.grid(alpha=0.3)

    earth_x = km_to_au(np.array(body_data["Earth"]["x_km"], dtype=float))
    earth_y = km_to_au(np.array(body_data["Earth"]["y_km"], dtype=float))
    moon_x = km_to_au(np.array(body_data["Moon"]["x_km"], dtype=float))
    moon_y = km_to_au(np.array(body_data["Moon"]["y_km"], dtype=float))

    ax.plot(earth_x, earth_y, "b--", lw=0.5, alpha=0.3, label="Earth orbit")
    ax.plot(moon_x, moon_y, "gray", lw=0.2, alpha=0.2, label="Moon orbit")
    ax.scatter(0, 0, s=150, c="gold", edgecolors="orange", zorder=5, label="Sun")

    earth_dot, = ax.plot([], [], "bo", ms=6, label="Earth")
    moon_dot, = ax.plot([], [], "go", ms=4, label="Moon")
    rocket_dot, = ax.plot([], [], "ro", ms=5, label="Rocket")
    rocket_trail, = ax.plot([], [], "r-", lw=1.0, alpha=0.6)
    trail_len = min(150, len(r_hist_au))

    info = ax.text(0.02, 0.98, "", transform=ax.transAxes, fontsize=8,
                   verticalalignment="top", bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.8))

    event_markers = {events[k]: k for k in ["swingby_day", "perihelion_day", "return_day"]}
    annotated = set()

    def init():
        earth_dot.set_data([], [])
        moon_dot.set_data([], [])
        rocket_dot.set_data([], [])
        rocket_trail.set_data([], [])
        info.set_text("")
        return earth_dot, moon_dot, rocket_dot, rocket_trail, info

    def animate(i):
        state = r_hist_au[i]
        r_s, r_e, r_m, r_r = state
        earth_dot.set_data([r_e[0]], [r_e[1]])
        moon_dot.set_data([r_m[0]], [r_m[1]])
        rocket_dot.set_data([r_r[0]], [r_r[1]])
        start = max(0, i - trail_len)
        trail = r_hist_au[start:i+1]
        rocket_trail.set_data([s[3][0] for s in trail], [s[3][1] for s in trail])

        t_days = t_hist[i] / 86400.0
        # Find closest event
        closest_event = None
        for ed, en in event_markers.items():
            if abs(t_days - ed) < 2.0 and en not in annotated:
                closest_event = en.replace("_", " ").title()
                annotated.add(en)

        ed = "" if closest_event is None else f"\n*** {closest_event} ***"
        info.set_text(f"Day {t_days:.1f}\n"
                      f"Rocket-Sun: {np.linalg.norm(r_r-r_s):.3f} AU\n"
                      f"Rocket-Moon: {np.linalg.norm(r_r-r_m)*AU_KM:.0f} km{ed}")
        return earth_dot, moon_dot, rocket_dot, rocket_trail, info

    n_frames = min(len(r_hist_au), int(duration_sec * fps))
    anim = animation.FuncAnimation(fig, animate, frames=n_frames,
                                    init_func=init, blit=True, interval=1000/fps)

    build_dir = repo_root / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    path = build_dir / filename

    print(f"[Anim] Writing ({n_frames} frames, {fps}fps)...")
    if shutil.which("ffmpeg"):
        anim.save(str(path), fps=fps, dpi=dpi, writer="ffmpeg",
                  extra_args=["-vcodec", "libx264", "-pix_fmt", "yuv420p"])
    else:
        path = path.with_suffix(".gif")
        anim.save(str(path), fps=fps, dpi=dpi, writer="pillow")
    plt.close(fig)
    print(f"[Anim] Saved to {path}")
    return str(path)


if __name__ == "__main__":
    # Quick test: 10s @ 10fps = 100 frames, keyframes always generated
    generate_orbit_animation(duration_sec=10, fps=10, dt_frame=DT_MAIN)
