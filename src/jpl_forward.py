"""
jpl_forward.py
===============
将 astroquery.jplhorizons 的请求转发到国内可访问的镜像站点。

在原 JPL Horizons 调用代码中，仅需在 import astroquery 后添加一行：
    import jpl_forward
即可自动完成 URL 重定向与 token 注入。

来源：ai4-math-tmp/week9/src/jpl_forward.py

安全说明：token 和代理 URL 存储在 config/proxy.ini（已 gitignored），
提交前确认未意外包含密钥。
"""

import configparser
from pathlib import Path
from astroquery.jplhorizons import HorizonsClass

# 从 gitignored 配置文件读取代理凭据
_config_path = Path(__file__).resolve().parents[1] / "config" / "proxy.ini"
FORWARD_URL = "http://localhost:18766/api/horizons.api"  # fallback
FORWARD_TOKEN = ""

if _config_path.exists():
    cfg = configparser.ConfigParser()
    cfg.read(_config_path)
    FORWARD_URL = cfg.get("proxy", "forward_url", fallback=FORWARD_URL)
    FORWARD_TOKEN = cfg.get("proxy", "forward_token", fallback=FORWARD_TOKEN)
else:
    print("[jpl_forward] WARNING: config/proxy.ini not found, using default localhost URL")

_original_request = HorizonsClass._request


def _patched_request(self, method, url, params=None, **kwargs):
    if params is None:
        params = {}
    if FORWARD_TOKEN:
        params["token"] = FORWARD_TOKEN
    url = FORWARD_URL
    return _original_request(self, method, url, params=params, **kwargs)


HorizonsClass._request = _patched_request
