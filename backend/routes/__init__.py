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
from . import otomasi_email  # noqa: F401
from . import pemetaan_tipe_kamar  # noqa: F401
from . import sinkronisasi_ketersediaan  # noqa: F401
from . import jenis_layanan  # noqa: F401
from . import konfigurasi_webhook  # noqa: F401
from . import pesan_whatsapp  # noqa: F401
from . import sinkronisasi_data_pms  # noqa: F401
from . import laporan_analitik  # noqa: F401
from . import rates  # noqa: F401
from . import tripay  # noqa: F401
from . import booking_requests  # noqa: F401
from . import issues  # noqa: F401
from . import telegram_bot  # noqa: F401
from . import scheduling  # noqa: F401
from . import push  # noqa: F401
from . import jadwal_kerja  # noqa: F401
from . import integrasi_ai_bot  # noqa: F401
from . import business_rules  # noqa: F401
