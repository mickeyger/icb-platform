"""Shared Jinja2Templates instance used by all routers."""
import os
from fastapi.templating import Jinja2Templates

from .deps import user_can

_BASE_DIR = os.path.dirname(__file__)
templates = Jinja2Templates(directory=os.path.join(_BASE_DIR, "templates"))
templates.env.globals["user_can"] = user_can
