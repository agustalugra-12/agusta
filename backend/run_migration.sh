#!/bin/bash
cd /root/agusta/backend
MONGO_URL="mongodb://localhost:27017" DB_NAME="pms" venv/bin/python3 -m scripts.migrate_multi_property
