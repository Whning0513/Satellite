"""
constants.py
=============
物理常数与天文常数，所有单位采用 km-s 体系。

常量来源：
- JPL ASTRODYN: https://ssd.jpl.nasa.gov/astro_glossary.html
- 项目题干 §3-§4
- 钱学森《星际航行概论》§5-§6
"""

# =========================
# 引力常数 GM (km³/s²)
# =========================

# 日心引力常数 (Sun gravitational parameter)
GM_SUN = 1.32712440041279419e11

# 地心引力常数 (Earth gravitational parameter)
GM_EARTH = 398600.435507

# 月心引力常数 (Moon gravitational parameter)
GM_MOON = 4902.800118

# 组合常数
GM_SEM = GM_SUN + GM_EARTH + GM_MOON  # Sun+Earth+Moon（用于二体验证）
GM_EARTH_MOON = GM_EARTH + GM_MOON    # Earth-Moon system

# =========================
# 天文距离单位
# =========================

# 1 天文单位 (km)
AU_KM = 149597870.7

# =========================
# 天体半径 (km)
# =========================

R_SUN = 696340.0            # 太阳半径
R_EARTH = 6371.0            # 地球半径
R_MOON = 1737.4             # 月球半径

# =========================
# 轨道参数
# =========================

R_EARTH_ORBIT = AU_KM       # 地球公转轨道半径 (1 AU)
V_EARTH_ORBIT = 29.80       # 地球公转速度 (km/s)，钱书 §6.3
V_ESCAPE_EARTH = 11.18      # 地球第二宇宙速度 (km/s)，钱书 §1.5
T_EARTH_YEAR = 365.25       # 地球公转周期 (天)

# =========================
# 月球参数
# =========================

R_MOON_SOI = 6.6e4          # 月球作用范围半径 (km)
R_MOON_ORBIT = 3.844e5      # 月地平均距离 (km)
T_MOON_MONTH = 27.322       # 恒星月周期 (天)
V_MOON_ORBIT = 1.022        # 月球公转速度 (km/s)

# =========================
# 数值积分参数
# =========================

DT_MAIN = 3600.0            # Velocity-Verlet 主步长 (s)
DT_REFINE = 60.0            # Velocity-Verlet 细化步长 (s)
CHECK_INTERVAL = 1000       # 守恒量检查间隔（步数）
ENERGY_TOL = 1e-6           # 一年内总能量相对漂移容忍上限

# =========================
# 设计变量范围
# =========================

# 近月距范围 (km): [月球半径+100, 50000]
R_M_MIN = R_MOON + 100.0    # 1837.4 km
R_M_MAX = 50000.0

# 近日距范围: [2*太阳半径, 0.4 * 地球轨道半径]
R_P_MIN = 2.0 * R_SUN       # 1.39268e6 km
R_P_MAX = 0.4 * AU_KM       # ~5.9839e7 km

# 飞行时间上限 (天)
T_MAX_DAYS = 2 * 365.25     # 2 年

# 再入相对速度上限 (km/s)
V_INF_MAX = 15.0

# 坐标变换
# 地球表面第二宇宙速度平方
V2_SQ = V_ESCAPE_EARTH ** 2
# 地球公转速度平方
VE_SQ = V_EARTH_ORBIT ** 2
