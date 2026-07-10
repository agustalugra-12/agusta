"""Route modules registration.

Importing this package will import every route module below, which in turn
registers all endpoints on the shared `api` router (defined in core.py).
"""
from . import auth  # noqa: F401
from . import rooms  # noqa: F401
from . import checkins  # noqa: F401
from . import inventory  # noqa: F401
from . import kasir  # noqa: F401
from . import expenses  # noqa: F401
from . import services  # noqa: F401
from . import bookings  # noqa: F401
from . import payments  # noqa: F401
from . import public  # noqa: F401
from . import reports  # noqa: F401
from . import misc  # noqa: F401
from . import ketersediaan  # noqa: F401
