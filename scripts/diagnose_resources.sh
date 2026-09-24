#!/usr/bin/env bash
# Read-only resource snapshot for the GoDaddy/cPanel (CloudLinux) account.
# Changes nothing and starts no long-running process.
# Usage (cPanel -> Terminal):  bash scripts/diagnose_resources.sh | tee tmp/diag.txt
PROJECT_DIR="${1:-$PWD}"
VENV_PY="$HOME/virtualenv/padosiagentdjango/src/3.11/bin/python"
line() { printf '\n==================== %s ====================\n' "$1"; }

line "TIME / LOAD"
date; uptime

line "LIMITS SEEN BY THIS SHELL (NPROC = processes+threads on CloudLinux)"
ulimit -a 2>/dev/null | grep -Ei "processes|virtual memory|open files"
grep -Ei "Max processes|Max address space" /proc/self/limits 2>/dev/null

line "PROCESS AND THREAD COUNT FOR $USER"
echo "processes: $(ps -u "$USER" -o pid= | wc -l)"
echo "threads (what NPROC counts): $(ps -u "$USER" -o nlwp= | awk '{s+=$1} END {print s}')"

line "PROCESSES BY MEMORY (RSS MB) — threads=nlwp, age=etime"
ps -u "$USER" -o pid,ppid,nlwp,rss,pcpu,etime,args --sort=-rss 2>/dev/null \
  | awk 'NR==1 {print; next} {$4=int($4/1024)"MB"; print}' | cut -c1-200 | head -25

line "PROCESSES BY CPU"
ps -u "$USER" -o pid,pcpu,pmem,etime,args --sort=-pcpu 2>/dev/null | cut -c1-200 | head -12

line "PASSENGER / PYTHON / BROWSER PROCESSES"
ps -u "$USER" -o pid,ppid,nlwp,rss,etime,args 2>/dev/null \
  | grep -Ei "passenger|python|wsgi|gunicorn|uvicorn|daphne|chrom|headless|node|playwright" | grep -v grep | cut -c1-200
echo "chromium processes: $(ps -u "$USER" -o args= | grep -ci '[c]hrom')"

line "TOTAL RSS OF ALL $USER PROCESSES"
ps -u "$USER" -o rss= | awk '{s+=$1} END {printf "%d MB\n", s/1024}'

line "MEMORY (host-wide view; the cPanel Resource Usage page shows the account's own limit)"
free -m 2>/dev/null

line "IS PLAYWRIGHT/CHROMIUM INSTALLED? (public OG images launch Chromium if yes)"
if [ -x "$VENV_PY" ]; then
  "$VENV_PY" -c "import playwright; print('playwright INSTALLED', playwright.__file__)" 2>/dev/null || echo "playwright not installed in venv"
else
  echo "venv python not found at $VENV_PY"
fi
ls -d "$HOME/.cache/ms-playwright"/* 2>/dev/null || echo "no ~/.cache/ms-playwright browsers"

line "DISK"
df -h "$HOME" 2>/dev/null
cd "$PROJECT_DIR" 2>/dev/null && du -sh cache logs media staticfiles tmp 2>/dev/null
echo "cache files: $(find cache -type f 2>/dev/null | wc -l)"

line "RECENT APP ERRORS"
for f in stderr.log logs/django.log; do
  [ -f "$f" ] && { echo "--- $f (last errors)"; grep -Ei "error|memory|resource|killed|cannot allocate|temporarily unavailable" "$f" | tail -15 | cut -c1-250; }
done

line "LAST DEPLOY"
cat tmp/.last_deployed_commit 2>/dev/null || echo "no deploy state yet"
git log --oneline -3 2>/dev/null
