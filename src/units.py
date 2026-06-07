"""
units.py
========
单位换算辅助函数和装饰器。

所有内部计算采用 km-s 体系：
- 距离: km
- 速度: km/s
- 时间: s 或 day (根据函数约定)
- 角度: rad
"""

import numpy as np

# =========================
# 基础换算因子
# =========================

AU_TO_KM = 149597870.7          # AU -> km
KM_TO_AU = 1.0 / AU_TO_KM       # km -> AU

DAY_TO_SEC = 86400.0            # day -> s
SEC_TO_DAY = 1.0 / DAY_TO_SEC   # s -> day

DEG_TO_RAD = np.pi / 180.0      # degree -> rad
RAD_TO_DEG = 180.0 / np.pi      # rad -> degree


def au_to_km(x: float) -> float:
    """AU -> km"""
    return x * AU_TO_KM


def km_to_au(x: float) -> float:
    """km -> AU"""
    return x * KM_TO_AU


def day_to_sec(x: float) -> float:
    """day -> s"""
    return x * DAY_TO_SEC


def sec_to_day(x: float) -> float:
    """s -> day"""
    return x * SEC_TO_DAY


def deg_to_rad(x: float) -> float:
    """degree -> rad"""
    return x * DEG_TO_RAD


def rad_to_deg(x: float) -> float:
    """rad -> degree"""
    return x * RAD_TO_DEG


def wrap_angle_rad(theta: float) -> float:
    """将角度限制在 [0, 2π) 范围内。"""
    return theta % (2.0 * np.pi)


def wrap_angle_deg(theta: float) -> float:
    """将角度限制在 [0, 360) 范围内。"""
    return theta % 360.0
