#!/bin/sh
# Export the PCBWAY manufacturing package to elec/build/fab and zip it.
# Usage: tools/export_fab.sh [kicad-cli path]
set -eu

cd "$(dirname "$0")/.."
CLI="${1:-kicad-cli}"
BOARD=elec/kicad/milsblo.kicad_pcb
SCH=elec/kicad/milsblo.kicad_sch
OUT=elec/build/fab

rm -rf "$OUT"
mkdir -p "$OUT/gerbers"

"$CLI" pcb export gerbers --no-x2 --subtract-soldermask --use-drill-file-origin \
  --layers "F.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts" \
  --output "$OUT/gerbers/" "$BOARD"
"$CLI" pcb export drill --format excellon --excellon-separate-th --excellon-oval-format route \
  --drill-origin plot --output "$OUT/gerbers/" "$BOARD"
# shellcheck disable=SC2016 # ${QUANTITY} is a KiCad field variable.
"$CLI" sch export bom \
  --fields 'Reference,Value,Footprint,${QUANTITY},LCSC Part,Partnumber' \
  --labels 'Reference,Value,Footprint,Qty,LCSC Part,Partnumber' \
  --group-by 'LCSC Part,Value' \
  --output "$OUT/milsblo-bom.csv" "$SCH"
"$CLI" pcb export pos --format csv --units mm --side front --smd-only \
  --use-drill-file-origin --output "$OUT/milsblo-pos.csv" "$BOARD"

(cd "$OUT/gerbers" && zip -q ../milsblo-gerbers.zip ./*)
