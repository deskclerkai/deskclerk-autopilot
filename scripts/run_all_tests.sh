#!/usr/bin/env bash
# 测试入口
#   ./scripts/run_all_tests.sh --quick   日常小改：接口回归 + 冒烟（几十秒）
#   ./scripts/run_all_tests.sh --full    交付前：五套全跑
set -u

MODE="full"
case "${1:-}" in
  --quick) MODE="quick" ;;
  --full|"") MODE="full" ;;
  *) echo "用法: $0 [--quick|--full]"; exit 2 ;;
esac

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PORTS=(7850 7851 7852 7853)
NAMES=(api ui edge smoke)
DBS=(/tmp/scrm-api.db /tmp/scrm-ui.db /tmp/scrm-edge.db /tmp/scrm-smoke.db)
PIDS=()
FAIL=0

cleanup() { for pid in ${PIDS[@]:-}; do kill "$pid" 2>/dev/null || true; done; }
trap cleanup EXIT

echo "== 模式：$MODE =="
for p in "${PORTS[@]}"; do lsof -ti:"$p" 2>/dev/null | xargs kill -9 2>/dev/null || true; done
for db in "${DBS[@]}"; do rm -f "$db" "$db-wal" "$db-shm"; done

need=1
[ "$MODE" = "full" ] && need=4
for i in $(seq 0 $((need-1))); do
  DB_PATH="${DBS[$i]}" nohup python3 -m uvicorn main:app --app-dir app \
    --port "${PORTS[$i]}" > "/tmp/scrm-${NAMES[$i]}.log" 2>&1 &
  PIDS+=($!)
done
sleep 5

run() {
  local name="$1"; shift
  local t0=$(date +%s)
  echo
  echo "===== $name ====="
  if "$@"; then echo "✅ $name 通过"; else echo "❌ $name 失败"; FAIL=1; fi
  echo "⏱ $(( $(date +%s) - t0 )) 秒"
}

run "接口回归 (api_tests)" python3 scripts/api_tests.py http://127.0.0.1:7850

if [ "$MODE" = "full" ]; then
  run "模糊测试 (fuzz_api)"  python3 scripts/fuzz_api.py  http://127.0.0.1:7850
  run "边界/安全/性能 (edge)" python3 scripts/edge_tests.py http://127.0.0.1:7852 "${DBS[2]}"
  run "界面测试 (ui_tests)"  python3 scripts/ui_tests.py  http://127.0.0.1:7851
  run "冒烟 (smoke)"         python3 scripts/smoke.py     http://127.0.0.1:7853
else
  run "冒烟 (smoke)"         python3 scripts/smoke.py     http://127.0.0.1:7850
  echo
  echo "ℹ️  quick 模式只跑接口 + 冒烟；交付前请跑 ./scripts/run_all_tests.sh --full"
fi

echo
if [ "$FAIL" -eq 0 ]; then echo "🎉 通过（$MODE）"; else echo "⛔ 有失败（$MODE）"; fi
exit "$FAIL"
