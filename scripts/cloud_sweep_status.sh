#!/bin/bash
# Live game-completion snapshot for the c_uct sweep across both VMs. Counts data
# rows (one per finished game) in each VM's out/sweep_*.csv — flushed per game, so
# it's real-time — and shows each box's current in-progress phase line + ETA.
ZONE=us-central1-a
TARGET=${TARGET:-50000}
total=0
for NAME in agricola-cuct-sweep-a agricola-cuct-sweep-b; do
  snap=$(gcloud compute ssh "$NAME" --zone="$ZONE" --quiet --command='
    cd ~ 2>/dev/null || exit 0
    for f in out/sweep_*.csv; do [ -e "$f" ] && printf "%s=%s " "$(basename "$f" .csv | sed s/sweep_//)" "$(grep -vc "^seed" "$f")"; done
    echo; tail -1 run.log 2>/dev/null' 2>/dev/null)
  if [ -z "$snap" ]; then echo "[$NAME] (gone / unreachable — likely finished + deleted)"; continue; fi
  d=$(echo "$snap" | head -1 | grep -o '=[0-9]*' | tr -d '=' | paste -sd+ - | bc)
  total=$((total + ${d:-0}))
  echo "[$NAME] ${d:-0}/25000 | per-level: $(echo "$snap" | head -1)"
  echo "        $(echo "$snap" | tail -1)"
done
echo "=== $(date +%H:%M:%S)  COMBINED $total / $TARGET ($(echo "scale=1; $total*100/$TARGET" | bc)%) ==="
