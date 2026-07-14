#!/bin/bash

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
