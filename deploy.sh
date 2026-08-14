#!/bin/bash

# set -e (2026-08-14, audit menemukan gap nyata: tidak ada gate build/test sama sekali
# sebelum restart/reload di bawah - `npm run build` gagal [exit code != 0] tetap lanjut ke
# `rm -rf /var/www/pmspelangi/*` [menghapus build LAMA yang masih bagus] + copy dari
# `build/*` yang stale/parsial, lalu tetap restart `pms-backend` [tidak terkait, jadi
# menutupi sinyal kegagalan asli] & reload nginx dgn state frontend yang rusak. `set -e`
# hentikan script di command manapun yang gagal (git pull/npm install/npm run build/dst) -
# tidak ada command di script ini yang MEMANG diniatkan boleh gagal & tetap lanjut, jadi
# aman dipasang global tanpa mengubah perilaku command yang lain.
set -e

echo "======================================"
echo "   Pelangi PMS Auto Deploy"
echo "======================================"

cd /root/agusta || exit

echo ""
echo "==> Pull terbaru dari GitHub..."
git pull

echo ""
echo "==> Build Frontend..."

cd frontend || exit

export NVM_DIR="$HOME/.nvm"
source "$NVM_DIR/nvm.sh"

nvm use 20

npm install --legacy-peer-deps

npm run build

echo ""
echo "==> Copy Frontend..."

rm -rf /var/www/pmspelangi/*
cp -r build/* /var/www/pmspelangi/

echo ""
echo "==> Restart Backend..."

systemctl restart pms-backend

echo ""
echo "==> Reload Nginx..."

systemctl reload nginx

echo ""
echo "======================================"
echo "Deploy Berhasil"
echo "======================================"

echo ""
echo "Website:"
echo "https://pelangihomestay.com"

echo ""
echo "API:"
echo "https://api.pelangihomestay.com"
