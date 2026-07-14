"""
Settings package.

Default export is development settings so `DJANGO_SETTINGS_MODULE=config.settings`
still works during exploration. Prefer explicit modules:

  config.settings.development
  config.settings.production
"""

from .development import *  # noqa: F401, F403
