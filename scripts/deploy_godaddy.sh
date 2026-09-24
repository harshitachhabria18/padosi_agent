#!/usr/bin/env bash
set -e

export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"

PROJECT_DIR="${1:-$PWD}"
DEPLOY_USER="${2:-$USER}"

echo "===================================================="
echo " Starting Deployment on GoDaddy Server"
echo " Time: $(date)"
echo " Project Directory: $PROJECT_DIR"
echo " Deploy User: $DEPLOY_USER"
echo "===================================================="

if [ -d "$PROJECT_DIR" ]; then
    cd "$PROJECT_DIR"
else
    echo "ERROR: Project directory $PROJECT_DIR does not exist!"
    exit 1
fi

echo "==> Current Working Directory: $(pwd)"
mkdir -p tmp

# One deploy at a time: two overlapping deploys would run pip/collectstatic
# twice in parallel inside the same CloudLinux resource limits.
if command -v flock >/dev/null 2>&1; then
    exec 9>"tmp/deploy.lock"
    if ! flock -w 900 9; then
        echo "ERROR: another deployment is still running; giving up after 15 minutes."
        exit 1
    fi
fi

# Heavy steps run at low CPU priority so live requests are served first.
NICE=""
if command -v nice >/dev/null 2>&1; then
    NICE="nice -n 10"
fi

echo "==> Pulling latest code from Git..."
git pull origin main
NEW_COMMIT="$(git rev-parse HEAD)"

echo "==> Detecting Python virtualenv..."
if [ -f "/home/$DEPLOY_USER/virtualenv/padosiagentdjango/src/3.11/bin/python" ]; then
    PY_BIN="/home/$DEPLOY_USER/virtualenv/padosiagentdjango/src/3.11/bin/python"
    PIP_BIN="/home/$DEPLOY_USER/virtualenv/padosiagentdjango/src/3.11/bin/pip"
elif [ -f "/home/m69qf6gyhm3n/virtualenv/padosiagentdjango/src/3.11/bin/python" ]; then
    PY_BIN="/home/m69qf6gyhm3n/virtualenv/padosiagentdjango/src/3.11/bin/python"
    PIP_BIN="/home/m69qf6gyhm3n/virtualenv/padosiagentdjango/src/3.11/bin/pip"
elif command -v python3 >/dev/null 2>&1; then
    PY_BIN="$(command -v python3)"
    PIP_BIN="$(command -v pip3 || command -v pip)"
else
    echo "ERROR: Could not locate Python binary!"
    exit 1
fi

echo "==> Using Python binary: $PY_BIN"
echo "==> Python version: $($PY_BIN --version 2>&1)"
echo "==> Using Pip binary: $PIP_BIN"

# Compare against the last deploy that finished successfully (not the
# pre-pull HEAD), so a deploy that failed half-way is fully redone next time.
STATE_FILE="tmp/.last_deployed_commit"
LAST_COMMIT="$(cat "$STATE_FILE" 2>/dev/null || true)"
RUN_ALL=0
if [ -z "$LAST_COMMIT" ] || ! git cat-file -e "${LAST_COMMIT}^{commit}" 2>/dev/null; then
    echo "==> No record of a previous successful deploy: running every step."
    RUN_ALL=1
    CHANGED=""
else
    CHANGED="$(git diff --name-only "$LAST_COMMIT" "$NEW_COMMIT")"
    echo "==> Files changed since last successful deploy ($LAST_COMMIT):"
    echo "${CHANGED:-  (none)}" | head -50
fi

changed() {
    [ "$RUN_ALL" = "1" ] && return 0
    echo "$CHANGED" | grep -Eq "$1"
}

REQ_CHANGED=0
if changed '^requirements\.txt$'; then REQ_CHANGED=1; fi

if [ "$REQ_CHANGED" = "1" ]; then
    echo "==> Installing / upgrading Python dependencies..."
    $NICE "$PIP_BIN" install --disable-pip-version-check -r requirements.txt
else
    echo "==> requirements.txt unchanged: skipping pip install."
fi

if [ "$REQ_CHANGED" = "1" ] || changed '/migrations/[^/]+\.py$'; then
    echo "==> Running database migrations..."
    $NICE "$PY_BIN" manage.py migrate --noinput
else
    echo "==> No migration files changed: skipping migrate."
fi

if [ "$REQ_CHANGED" = "1" ] || [ ! -f staticfiles/staticfiles.json ] \
        || changed '(^|/)static/|^padosi_agent/(settings|storage)\.py$'; then
    echo "==> Collecting static files..."
    $NICE "$PY_BIN" manage.py collectstatic --noinput
else
    echo "==> No static files changed: skipping collectstatic."
fi

echo "==> Restarting Passenger WSGI application..."
touch tmp/restart.txt

echo "$NEW_COMMIT" > "$STATE_FILE"

echo "===================================================="
echo " Deployment completed successfully! ($NEW_COMMIT)"
echo " Time: $(date)"
echo "===================================================="
