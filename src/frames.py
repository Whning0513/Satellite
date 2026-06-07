"""
frames.py
=========
参考系转换模块 (Reference Frame Transformations).

集中管理所有参考系定义与转换，避免在各模块中散落临时代码。

支持的参考系：
  - barycentric_inertial : SSB (Solar System Barycenter) 惯性系
  - heliocentric         : 日心相对坐标（非惯性系，含 indirect term）
  - ecliptic_2d          : J2000 黄道面 (x-y) 投影

单位体系：km, km/s（除非特别注明）。
"""

import numpy as np
from typing import List, Tuple, Optional


# =========================
# 1. 参考系定义
# =========================

FRAME_BARYCENTRIC = "barycentric_inertial"
FRAME_HELIOCENTRIC = "heliocentric_relative"
FRAME_2D = "ecliptic_2d"

BODY_NAMES_DEFAULT = ["Sun", "Earth", "Moon"]


def to_heliocentric(
    r_list: List[np.ndarray],
    v_list: List[np.ndarray],
    sun_idx: int = 0,
) -> Tuple[List[np.ndarray], List[np.ndarray]]:
    """将 SSB 惯性系状态转换为日心相对坐标。

    r_i^helio = r_i - r_sun
    v_i^helio = v_i - v_sun

    Parameters
    ----------
    r_list : list of ndarray
        SSB 位置列表，r_list[sun_idx] 为太阳。
    v_list : list of ndarray
        SSB 速度列表。
    sun_idx : int
        太阳在列表中的索引，默认 0。

    Returns
    -------
    (r_helio, v_helio) : list of ndarray
        日心相对坐标。太阳自身为 (0, 0)。
    """
    r_sun = r_list[sun_idx]
    v_sun = v_list[sun_idx]
    r_h = [ri - r_sun for ri in r_list]
    v_h = [vi - v_sun for vi in v_list]
    # 太阳自身归零
    r_h[sun_idx] = np.zeros_like(r_sun)
    v_h[sun_idx] = np.zeros_like(v_sun)
    return r_h, v_h


def to_barycentric(
    r_helio: List[np.ndarray],
    v_helio: List[np.ndarray],
    r_sun: np.ndarray,
    v_sun: np.ndarray,
    sun_idx: int = 0,
) -> Tuple[List[np.ndarray], List[np.ndarray]]:
    """将日心相对坐标转回 SSB 惯性系。

    Parameters
    ----------
    r_helio, v_helio : list of ndarray
        日心相对位置/速度。太阳处应为 (0,0)。
    r_sun, v_sun : ndarray
        太阳的 SSB 位置/速度。
    sun_idx : int

    Returns
    -------
    (r_bary, v_bary) : list of ndarray
    """
    r_b = [r_sun + rh if i != sun_idx else r_sun.copy()
           for i, rh in enumerate(r_helio)]
    v_b = [v_sun + vh if i != sun_idx else v_sun.copy()
           for i, vh in enumerate(v_helio)]
    return r_b, v_b


def project_to_2d(
    r_list: List[np.ndarray],
    v_list: List[np.ndarray],
) -> Tuple[List[np.ndarray], List[np.ndarray]]:
    """将三维向量投影到 J2000 黄道平面 (x-y)。

    Parameters
    ----------
    r_list, v_list : list of (3,) ndarray

    Returns
    -------
    (r_2d, v_2d) : list of (2,) ndarray
    """
    r_2d = [r[:2].copy() for r in r_list]
    v_2d = [v[:2].copy() for v in v_list]
    return r_2d, v_2d


def relative_state(
    r: np.ndarray,
    v: np.ndarray,
    r_center: np.ndarray,
    v_center: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray]:
    """计算某天体相对于中心天体的状态。

    r_rel = r - r_center
    v_rel = v - v_center

    Parameters
    ----------
    r, v : ndarray
        天体的位置/速度向量。
    r_center, v_center : ndarray
        中心天体的位置/速度向量。

    Returns
    -------
    (r_rel, v_rel) : ndarray
    """
    return r - r_center, v - v_center


def get_barycentric_state(
    r_helio_list: List[np.ndarray],
    v_helio_list: List[np.ndarray],
    body_names: List[str],
    body_data: dict,
    epoch_idx: int,
    sun_name: str = "Sun",
) -> Tuple[List[np.ndarray], List[np.ndarray]]:
    """从日心相对状态 + Horizons 历表重构 SSB 绝对状态。

    用于将日心相对积分结果转回 SSB 以便与历表对比。

    Parameters
    ----------
    r_helio_list, v_helio_list : list of ndarray
    body_names : list of str
    body_data : dict
        Horizons 历表（获取太阳 SSB 状态）。
    epoch_idx : int
        时刻的历表索引。
    sun_name : str

    Returns
    -------
    (r_bary, v_bary) : list of ndarray
    """
    from horizons import state_at_index
    r_sun, v_sun = state_at_index(body_data, sun_name, epoch_idx)
    return to_barycentric(r_helio_list, v_helio_list, r_sun, v_sun)


# =========================
# 2. 状态向量单位验证
# =========================

def describe_frame(r_list: List[np.ndarray], v_list: List[np.ndarray],
                   body_names: List[str] = None) -> str:
    """输出当前参考系的概要描述。"""
    if body_names is None:
        body_names = [f"Body{i}" for i in range(len(r_list))]

    lines = ["Frame state summary:"]
    for i, name in enumerate(body_names):
        r_norm = np.linalg.norm(r_list[i])
        v_norm = np.linalg.norm(v_list[i])
        lines.append(f"  {name:6s}: |r|={r_norm:.4e} km, |v|={v_norm:.6e} km/s")
    return "\n".join(lines)


def frame_summary(result: dict) -> dict:
    """提取残差结果中的参考系信息。"""
    return {
        "frame": result.get("frame", "unknown"),
        "dimension": result.get("dimension", "3d"),
        "dt_s": result.get("dt_s", None),
        "indirect_term": result.get("indirect_term", None),
    }
