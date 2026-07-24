"""Bootstrap bersama untuk seluruh test suite (2026-07-24, diperbaiki saat audit kesiapan
produksi - sebelumnya tiap file test punya logika baca .env sendiri-sendiri, hardcode path
'/app/backend/.env'/'/app/frontend/.env' dari environment pengembangan lain yang TIDAK ADA
di server produksi ini, jadi seluruh suite gagal total sebelum sempat menjalankan satu test
pun. Root cause sebenarnya lebih dalam dari sekadar path salah: server produksi ini TIDAK
PAKAI file .env sama sekali (kredensial di-set langsung sebagai systemd Environment, lihat
/etc/systemd/system/pms-backend.service) - jadi baca file .env akan SELALU gagal di sini
apapun path-nya, satu-satunya sumber yang benar adalah environment variable.

PENTING - keamanan data produksi: test-test ini membuat/mengubah/menghapus data sungguhan
lewat HTTP API (booking, tamu, dst). JANGAN PERNAH jalankan dengan REACT_APP_BACKEND_URL
mengarah ke server produksi (api.pelangihomestay.com) - itu akan mencampur data test palsu
dengan data tamu asli. Wajib disiapkan server terpisah yang mengarah ke database terpisah
(mis. DB_NAME=pms_test yang sudah disediakan) sebelum menjalankan suite ini - BUKAN dengan
menyalakan instance backend baru sembarangan (startup hook bisa menimpa password admin live
kalau salah konfigurasi), tapi lewat proses yang sengaja disiapkan & diverifikasi aman."""
import os


def get_env(key: str) -> str:
    """Satu-satunya sumber kebenaran config test: environment variable. TIDAK ADA fallback
    ke file .env manapun (server ini tidak pakai file itu) - gagal keras & jelas kalau
    belum diset, supaya tidak pernah diam-diam menjalankan test ke target yang salah."""
    val = os.environ.get(key)
    if not val:
        raise RuntimeError(
            f"Environment variable '{key}' belum diset. Test suite ini WAJIB dijalankan "
            f"terhadap server test terpisah (bukan produksi) - export {key} dulu sebelum "
            f"menjalankan pytest. Lihat docstring conftest.py untuk detail keamanan."
        )
    return val.rstrip("/")
