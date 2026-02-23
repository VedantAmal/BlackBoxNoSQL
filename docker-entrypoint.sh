#!/bin/bash
set -eo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=================================================="
echo "  BlackBox CTF Platform - Docker Entrypoint"
echo -e "==================================================${NC}"
echo ""

# Wait for database to be ready
echo -e "${YELLOW}Waiting for database...${NC}"
# Extract host and port from MONGODB_URI if possible, otherwise default
# Simple parsing for standard connection string
if [[ "$MONGODB_URI" =~ mongodb://([^:]+):([^@]+)@([^:]+):([0-9]+) ]]; then
    DB_HOST="${BASH_REMATCH[3]}"
    DB_PORT="${BASH_REMATCH[4]}"
elif [[ "$MONGODB_URI" =~ mongodb://([^:]+):([0-9]+) ]]; then
    DB_HOST="${BASH_REMATCH[1]}"
    DB_PORT="${BASH_REMATCH[2]}"
else
    DB_HOST="mongo"
    DB_PORT="27017"
fi

TIMEOUT=60
COUNT=0

# First wait for port to be open
until nc -z "$DB_HOST" "$DB_PORT" 2>/dev/null; do
    COUNT=$((COUNT+1))
    if [ $COUNT -ge $TIMEOUT ]; then
        echo -e "${RED}  ✗ Database port connection timeout after ${TIMEOUT}s${NC}"
        exit 1
    fi
    echo -e "${YELLOW}  Database port is unavailable - sleeping (${COUNT}/${TIMEOUT})${NC}"
    sleep 1
done
echo -e "${GREEN}  ✓ Database port is open${NC}"
echo -e "${GREEN}  ✓ Database is ready${NC}"

# Wait for Redis to be ready
echo -e "${YELLOW}Waiting for Redis...${NC}"
REDIS_HOST="${REDIS_HOST:-cache}"
REDIS_PORT="${REDIS_PORT:-6379}"
TIMEOUT=60
COUNT=0

until nc -z "$REDIS_HOST" "$REDIS_PORT" 2>/dev/null; do
    COUNT=$((COUNT+1))
    if [ $COUNT -ge $TIMEOUT ]; then
        echo -e "${RED}  ✗ Redis connection timeout after ${TIMEOUT}s${NC}"
        exit 1
    fi
    echo -e "${YELLOW}  Redis is unavailable - sleeping (${COUNT}/${TIMEOUT})${NC}"
    sleep 1
done
echo -e "${GREEN}  ✓ Redis is ready${NC}"

# Create upload directories (with error handling for permission issues)
echo -e "${YELLOW}Setting up upload directories...${NC}"
UPLOAD_DIR="${UPLOAD_FOLDER:-/var/uploads}"
LOG_DIR="${LOG_FOLDER:-/var/log/CTFPlatform}"

# Try to create directories, ignore errors if they exist or we don't have permissions
mkdir -p "$UPLOAD_DIR/challenges" 2>/dev/null || true
mkdir -p "$UPLOAD_DIR/temp" 2>/dev/null || true
mkdir -p "$UPLOAD_DIR/avatars" 2>/dev/null || true
mkdir -p "$LOG_DIR" 2>/dev/null || true

# Check if we can write to upload directory
if [ -w "$UPLOAD_DIR" ]; then
    echo -e "${GREEN}  ✓ Upload directory is writable${NC}"
else
    echo -e "${YELLOW}  ⚠ Upload directory has limited permissions, but may work with volume mount${NC}"
fi

echo -e "${GREEN}  ✓ Directories setup complete${NC}"

# Initialize database if needed
echo -e "${YELLOW}Checking database initialization...${NC}"
if [ "${AUTO_INIT_DB:-false}" = "true" ]; then
    if [ "${WITH_SAMPLE_DATA:-false}" = "true" ]; then
        echo -e "${YELLOW}Initializing database with sample data...${NC}"
        python init_db.py
    else
        echo -e "${YELLOW}Initializing database without sample data...${NC}"
        python init_db.py --no-sample-data
    fi
    echo -e "${GREEN}  ✓ Database initialized${NC}"
else
    echo -e "${YELLOW}  Creating database tables only (no sample data)...${NC}"
    # In MongoEngine, explicit table creation is not needed.
    # We just ensure indexes are created.
    python -c "from app import create_app; from models import db; app = create_app(); app.app_context().push(); print('✓ Database ready (NoSQL)')"
fi

echo ""
echo -e "${GREEN}=================================================="
echo "  Starting BlackBox CTF Platform"
echo -e "==================================================${NC}"
echo ""

# Ensure Docker settings schema & defaults exist (non-destructive)
echo -e "${YELLOW}Ensuring Docker settings schema exists...${NC}"
python scripts/ensure_docker_schema.py || echo -e "${RED}Warning: ensure_docker_schema.py failed (continuing)${NC}"
echo -e "${GREEN}  ✓ Docker schema check complete${NC}"


# Start application with Gunicorn
exec gunicorn \
    --config gunicorn.conf.py \
    --bind 0.0.0.0:8000 \
    --access-logfile "${ACCESS_LOG:--}" \
    --error-logfile "${ERROR_LOG:--}" \
    --log-level info \
    --preload \
    "app:create_app()"
