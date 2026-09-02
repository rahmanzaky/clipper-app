#!/usr/bin/env bash
# Real end-to-end smoke test against a running backend — formalizes the manual
# curl-based verification that's been re-derived from scratch, ad hoc, every
# development session. Requires the backend already running at API_URL (this
# script does not start it, since the right startup env vars — WHISPER_MODEL,
# HF_HUB_DISABLE_XET — depend on whether you want a fast test run or a real
# accuracy run, and that choice belongs to whoever's running this).
#
# Usage:
#   ./scripts/smoke_test.sh
#   API_URL=http://127.0.0.1:8000 ./scripts/smoke_test.sh
#
# Exits non-zero on the first failed check.

set -uo pipefail

API_URL="${API_URL:-http://127.0.0.1:8000}"
TEST_VIDEO_URL="${TEST_VIDEO_URL:-https://www.youtube.com/watch?v=jNQXAC9IVRw}"
PASS=0
FAIL=0

check() {
  local desc="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then
    echo "  OK   $desc"
    PASS=$((PASS + 1))
  else
    echo "  FAIL $desc (expected $expected, got $actual)"
    FAIL=$((FAIL + 1))
  fi
}

echo "== Backend reachable =="
code=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL/api/profiles")
check "GET /api/profiles" "200" "$code"

echo
echo "== 404 handling =="
code=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL/api/jobs/00000000-0000-0000-0000-000000000000")
check "GET /api/jobs/<nonexistent>" "404" "$code"

echo
echo "== Submit a real job and wait for it to finish =="
resp=$(curl -s -X POST "$API_URL/api/process" -H "Content-Type: application/json" \
  -d "{\"url\":\"$TEST_VIDEO_URL\",\"topics\":[\"elephant\"],\"min_duration\":5,\"max_duration\":60,\"hashtag\":\"\"}")
job=$(echo "$resp" | python3 -c "import json,sys;print(json.load(sys.stdin)['job_id'])" 2>/dev/null)
if [ -z "$job" ]; then
  echo "  FAIL Could not submit job — response was: $resp"
  FAIL=$((FAIL + 1))
  echo
  echo "$PASS passed, $FAIL failed"
  exit 1
fi
echo "  job_id=$job"

stage=""
for i in $(seq 1 60); do
  stage=$(curl -s "$API_URL/api/jobs/$job" | python3 -c "import json,sys;print(json.load(sys.stdin)['stage'])" 2>/dev/null)
  [ "$stage" = "done" ] || [ "$stage" = "error" ] && break
  sleep 3
done
check "Job reaches a terminal stage within 3 minutes" "done" "$stage"

if [ "$stage" != "done" ]; then
  echo
  echo "Job did not complete — skipping the rest (nothing to test against)."
  echo "$PASS passed, $FAIL failed"
  exit 1
fi

job_json=$(curl -s "$API_URL/api/jobs/$job")
clip_count=$(echo "$job_json" | python3 -c "import json,sys;print(len(json.load(sys.stdin)['clips']))")
echo "  clips found: $clip_count"

echo
echo "== Manual clip creation =="
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$API_URL/api/jobs/$job/manual-clip" \
  -H "Content-Type: application/json" -d '{"start":1,"end":6}')
check "POST manual-clip" "200" "$code"

echo
echo "== Editing endpoints (against clip 0) =="
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$API_URL/api/clips/$job/0/trim" \
  -H "Content-Type: application/json" -d '{"start":1,"end":8}')
check "POST trim" "200" "$code"

code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$API_URL/api/clips/$job/0/reposition" \
  -H "Content-Type: application/json" -d '{"crop_center_frac":0.4}')
check "POST reposition" "200" "$code"

code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$API_URL/api/clips/$job/0/captions" \
  -H "Content-Type: application/json" -d '{"lines":[{"text":"smoke test caption","start":0,"end":2}]}')
check "POST captions" "200" "$code"

code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$API_URL/api/clips/$job/999/trim" \
  -H "Content-Type: application/json" -d '{"start":0,"end":5}')
check "POST trim on nonexistent clip -> 404" "404" "$code"

echo
echo "== Download all =="
code=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL/api/jobs/$job/download-all")
check "GET download-all" "200" "$code"

echo
echo "== Maintenance =="
code=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL/api/maintenance/stats")
check "GET maintenance/stats" "200" "$code"

code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$API_URL/api/maintenance/cleanup?max_age_hours=0")
check "POST maintenance/cleanup (forced)" "200" "$code"

echo
echo "== Profiles =="
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$API_URL/api/profiles" \
  -H "Content-Type: application/json" \
  -d '{"name":"_smoke_test","topics":["a"],"min_duration":5,"max_duration":60,"hashtag":""}')
check "POST profiles (save)" "200" "$code"

code=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE "$API_URL/api/profiles/_smoke_test")
check "DELETE profiles/_smoke_test" "200" "$code"

echo
echo "======================================"
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
