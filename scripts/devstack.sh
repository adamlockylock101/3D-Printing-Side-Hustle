#!/usr/bin/env bash
# Bring up a complete local stack for development: Postgres, the worker, and the storefront.
#
# This exists because the interesting bugs only show up with real data flowing through both
# services. It is a development convenience, not a deployment path — see docs/setup.md for that.
#
#   scripts/devstack.sh up       start everything and print the URLs
#   scripts/devstack.sh down     stop everything
#   scripts/devstack.sh restart  stop and start (the worker does not hot-reload)
#   scripts/devstack.sh seed    put realistic orders through the real customer flow
#   scripts/devstack.sh reset   drop and recreate the database, then reseed

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PG_BIN="${PG_BIN:-/usr/lib/postgresql/16/bin}"
PGDATA="${PGDATA:-/var/lib/postgresql/devstack}"
PG_PORT="${PG_PORT:-5433}"
WORKER_PORT="${WORKER_PORT:-8000}"
WEB_PORT="${WEB_PORT:-3000}"
RUN="$ROOT/.devstack"

export DATABASE_URL="postgresql://printshop@127.0.0.1:${PG_PORT}/printshop"
export WORKER_URL="http://localhost:${WORKER_PORT}"
export NEXT_PUBLIC_SITE_URL="http://localhost:${WEB_PORT}"
export ADMIN_TOKEN="${ADMIN_TOKEN:-demo-token}"
export PRINTSHOP_ROOT="$ROOT"

mkdir -p "$RUN"

pg_running() { "$PG_BIN/pg_isready" -h 127.0.0.1 -p "$PG_PORT" -q 2>/dev/null; }

# Kill whatever holds a port. More reliable than a pid file: a dev server that respawns, or one
# started outside this script, leaves a stale pid behind and the old process keeps serving.
# The bracketed character class stops the pattern matching the shell running this script —
# `pkill -f uvicorn` will happily kill its own parent, which is a memorable way to lose a
# terminal. Matching on the port too keeps it to the process this script started.
kill_matching() {
  local pattern="$1"
  local pids
  pids="$(pgrep -f "$pattern" | grep -v "^$$\$" || true)"
  [ -z "$pids" ] && return 0
  kill $pids 2>/dev/null || true
  sleep 2
  pids="$(pgrep -f "$pattern" | grep -v "^$$\$" || true)"
  [ -n "$pids" ] && kill -9 $pids 2>/dev/null || true
  return 0
}

stop_services() {
  kill_matching "uvicorn worker[.]api:app --app-dir src --port $WORKER_PORT"
  kill_matching "next[-]server"
  kill_matching "next[ ]dev -p $WEB_PORT"
  rm -f "$RUN"/*.pid
}

start_pg() {
  if pg_running; then echo "postgres already up on $PG_PORT"; return; fi
  if [ ! -d "$PGDATA/base" ]; then
    # initdb refuses to run as root, so the cluster is owned by the postgres system user.
    mkdir -p "$PGDATA"; chown postgres:postgres "$PGDATA"; chmod 700 "$PGDATA"
    su postgres -c "PATH=$PG_BIN:\$PATH initdb -D $PGDATA -U printshop --auth=trust" >/dev/null
  fi
  su postgres -c "PATH=$PG_BIN:\$PATH pg_ctl -D $PGDATA -l $PGDATA/server.log \
      -o '-p $PG_PORT -h 127.0.0.1' -w start" >/dev/null
  "$PG_BIN/psql" -h 127.0.0.1 -p "$PG_PORT" -U printshop -d postgres \
      -c "create database printshop" >/dev/null 2>&1 || true
  echo "postgres up on $PG_PORT"
}

start_worker() {
  if curl -sf -m 2 "$WORKER_URL/health" >/dev/null 2>&1; then echo "worker already up"; return; fi
  ( cd "$ROOT/services/worker" \
    && nohup .venv/bin/python -m uvicorn worker.api:app --app-dir src --port "$WORKER_PORT" \
       > "$RUN/worker.log" 2>&1 & echo $! > "$RUN/worker.pid" )
  for _ in $(seq 30); do curl -sf -m 2 "$WORKER_URL/health" >/dev/null 2>&1 && break; sleep 1; done
  echo "worker up on $WORKER_PORT"
}

start_web() {
  if curl -sf -m 2 "http://localhost:$WEB_PORT/" >/dev/null 2>&1; then echo "web already up"; return; fi
  ( cd "$ROOT/apps/web" && npx prisma db push --skip-generate >/dev/null 2>&1 || true )
  ( cd "$ROOT/apps/web" \
    && nohup npx next dev -p "$WEB_PORT" > "$RUN/web.log" 2>&1 & echo $! > "$RUN/web.pid" )
  for _ in $(seq 60); do curl -sf -m 2 "http://localhost:$WEB_PORT/" >/dev/null 2>&1 && break; sleep 1; done
  echo "web up on $WEB_PORT"
}

case "${1:-up}" in
  up)
    start_pg; start_worker; start_web
    echo
    echo "  storefront   http://localhost:$WEB_PORT"
    echo "  operator     http://localhost:$WEB_PORT/admin   (token: $ADMIN_TOKEN)"
    echo "  worker docs  $WORKER_URL/docs"
    ;;
  down)
    stop_services
    su postgres -c "PATH=$PG_BIN:\$PATH pg_ctl -D $PGDATA stop" >/dev/null 2>&1 || true
    echo "stopped"
    ;;
  restart)
    stop_services
    start_pg; start_worker; start_web
    echo "restarted"
    ;;
  seed)
    "$ROOT/services/worker/.venv/bin/python" "$ROOT/scripts/seed_demo.py"
    ;;
  reset)
    "$PG_BIN/psql" -h 127.0.0.1 -p "$PG_PORT" -U printshop -d postgres \
      -c "drop database if exists printshop" >/dev/null
    "$PG_BIN/psql" -h 127.0.0.1 -p "$PG_PORT" -U printshop -d postgres \
      -c "create database printshop" >/dev/null
    ( cd "$ROOT/apps/web" && npx prisma db push --skip-generate >/dev/null )
    "$ROOT/services/worker/.venv/bin/python" "$ROOT/scripts/seed_demo.py"
    ;;
  *) echo "usage: devstack.sh [up|down|restart|seed|reset]"; exit 1 ;;
esac
