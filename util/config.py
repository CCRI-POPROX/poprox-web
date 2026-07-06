import logging
from os import environ as env

from flask.helpers import get_debug_flag

logger = logging.getLogger(__name__)


def require_secret(key, dev_default) -> str:
    """Return the secret from the environment. Outside of debug mode a missing or
    empty value raises instead of falling back to the hardcoded default.
    """
    value = env.get(key)
    if value:
        return value
    # get_debug_flag() instead of app.debug -- this can run before the app exists.
    if not get_debug_flag():
        raise RuntimeError(f"{key} must be set when not running in debug mode")
    logger.warning("%s not set, falling back to insecure dev default", key)
    return dev_default
