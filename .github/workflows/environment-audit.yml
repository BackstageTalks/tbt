name: Environment coverage audit

on:
  workflow_dispatch:
    inputs:
      start:
        description: "Optional start UTC/date (inclusive); blank = all history"
        required: false
        default: ""
        type: string
      end:
        description: "Optional end UTC/date (exclusive); blank = all history"
        required: false
        default: ""
        type: string

permissions:
  contents: read

# Audits may run while environment enrichment is still checkpointing. The
# release reader verifies checksums and retries the narrow commit race, so we
# can inspect the latest committed partial coverage without blocking the writer.
concurrency:
  group: tbt-environment-audit
  cancel-in-progress: true

jobs:
  audit:
    runs-on: ubuntu-latest
    timeout-minutes: 60
    env:
      PYTHONPATH: api
      TBT_DATA_REPOSITORY: ${{ vars.TBT_DATA_REPOSITORY || 'BackstageTalks/tbt-data' }}
      GH_TOKEN: ${{ secrets.TBT_DATA_GH_TOKEN }}

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
          cache-dependency-path: api/requirements-train.txt

      - name: Install audit dependencies
        run: |
          set -euo pipefail
          python -m pip install -r api/requirements-train.txt
          python -m compileall -q api scripts

      - name: Preflight private history access
        shell: bash
        run: |
          set -euo pipefail
          test -n "$GH_TOKEN" || { echo 'Missing TBT_DATA_GH_TOKEN'; exit 1; }
          visibility="$(gh repo view "$TBT_DATA_REPOSITORY" --json visibility -q '.visibility')"
          test "$visibility" = "PRIVATE" || { echo 'Refusing non-private data repository'; exit 1; }

      - name: Audit current tbt-data-v1 release
        shell: bash
        run: |
          set -euo pipefail
          mkdir -p .cache/tbt
          ARGS=(
            --data-repository "$TBT_DATA_REPOSITORY"
            --report ".cache/tbt/environment_audit_report.json"
          )
          if [[ -n "${{ inputs.start }}" ]]; then ARGS+=(--start "${{ inputs.start }}"); fi
          if [[ -n "${{ inputs.end }}" ]]; then ARGS+=(--end "${{ inputs.end }}"); fi
          python scripts/audit_environment_release.py "${ARGS[@]}" | tee .cache/tbt/environment_audit.log

      - name: Publish readable summary
        shell: bash
        run: |
          python - <<'PY' >> "$GITHUB_STEP_SUMMARY"
          import json
          from pathlib import Path
          report=json.loads(Path('.cache/tbt/environment_audit_report.json').read_text())
          o=report['overall']; c=o['coverage']
          print('## Environment coverage')
          print('')
          print('| Metric | Count | Coverage |')
          print('|---|---:|---:|')
          for label,key,ckey in [
              ('Canonical completed','total',None),
              ('Environment present','with_environment','environment'),
              ('Venue resolved','venue_resolved','venue_resolved'),
              ('Weather object','with_weather_object','weather_object'),
              ('Usable weather','usable_weather','usable_weather'),
          ]:
              count=o.get(key,0)
              coverage='—' if ckey is None else f"{c.get(ckey,0):.2%}"
              print(f'| {label} | {count:,} | {coverage} |')
          print(f"| Expected indoor no-weather | {o.get('indoor_resolved_no_weather_expected',0):,} | — |")
          print(f"| Unresolved venue | {o.get('unresolved',0):,} | — |")
          print(f"| Missing environment | {o.get('missing_environment',0):,} | — |")
          print('')
          print('### By tour')
          for tour,row in report.get('by_tour',{}).items():
              print(f"- **{tour}**: {row['total']:,} matches · venue {row['coverage']['venue_resolved']:.2%} · usable weather {row['coverage']['usable_weather']:.2%}")
          print('')
          top=o.get('top_unresolved_tournaments') or []
          if top:
              print('### Top unresolved tournaments')
              for name,count in top[:15]:
                  print(f'- {name}: {count:,}')
          PY

      - uses: actions/upload-artifact@v4
        with:
          name: environment-audit-${{ github.run_id }}
          path: |
            .cache/tbt/environment_audit_report.json
            .cache/tbt/environment_audit.log
          if-no-files-found: error
          retention-days: 14
