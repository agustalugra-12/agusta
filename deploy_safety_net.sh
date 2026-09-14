#!/bin/bash
# (2026-09-14) Jaring pengaman deploy: GitHub Actions SESEKALI gagal MEMICU workflow saat
# push (webhook internal GitHub drop — sisi GitHub, tak bisa diperbaiki dari sini). Akibatnya
# commit sudah di origin/main tapi TIDAK PERNAH ter-deploy. Cron kecil ini (tiap 5 menit) cek:
# apakah origin/main lebih baru dari SHA yang terakhir BERHASIL ter-deploy (.last_deployed_sha,
# ditulis deploy.sh di akhir)? Kalau ya → jalankan deploy.sh (yang sudah dilindungi flock, jadi
# aman walau Actions kebetulan juga sedang jalan — yang kedua keluar bersih). Efek: kalau
# GitHub drop sebuah trigger, VPS auto-recover sendiri dalam ~5 menit tanpa perlu deploy manual.
cd /root/agusta || exit 0
git fetch origin main --quiet 2>/dev/null || exit 0
latest=$(git rev-parse origin/main 2>/dev/null)
deployed=$(cat /root/agusta/.last_deployed_sha 2>/dev/null || echo "")
if [ -n "$latest" ] && [ "$latest" != "$deployed" ]; then
  echo "$(date '+%F %T') origin/main=$latest != deployed=${deployed:-<none>} → jalankan deploy.sh"
  bash /root/agusta/deploy.sh
else
  echo "$(date '+%F %T') sudah sinkron ($latest) — tak ada yang perlu di-deploy"
fi
