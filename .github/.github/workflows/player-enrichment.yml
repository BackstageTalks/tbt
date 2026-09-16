name: Player card enrichment

on:
  workflow_dispatch:
    inputs:
      max_players:
        description: "Maximum current players to inspect (0 = all)"
        required: true
        default: "0"
        type: string
      max_photo_requests:
        description: "Maximum player-image API requests this run"
        required: true
        default: "250"
        type: string
      max_fallback_ranking_requests:
        description: "Per-player ranking fallbacks after ATP/WTA snapshots"
        required: true
        default: "100"
        type: string
      max_player_detail_requests:
        description: "Maximum current player-detail API requests this run"
        required: true
        default: "250"
        type: string
      max_tournament_logo_requests:
        description: "Maximum tournament-logo API requests this run"
        required: true
        default: "120"
        type: string
      refresh_current_feed:
        description: "Refresh current fixtures/predictions first so Form LXX, surface form, H2H context and tournament IDs use the current code"
        required: true
        default: true
        type: boolean
      max_refresh_requests:
        description: "Provider request cap for current prediction refresh"
        required: true
        default: "750"
        type: string
      market_odds_max_events:
        description: "Current events to enrich with provider-1 odds during refresh"
        required: true
        default: "120"
        type: string
      refresh_photos:
        description: "Re-download photos that are already cached"
        required: true
        default: false
        type: boolean

permissions:
  contents: read

concurrency:
  group: tbt-player-assets-writer
  cancel-in-progress: false

jobs:
  enrich:
    runs-on: ubuntu-latest
    timeout-minutes: 120
    # The workflow still serializes player-asset writers globally, while this
    # job also shares the history/prediction writer lock with data.yml because
    # it refreshes the current prediction candidate before enrichment.
    concurrency:
      group: tbt-history-data-writer
      cancel-in-progress: false
    env:
      PYTHONPATH: api
      TBT_DATA_REPOSITORY: ${{ vars.TBT_DATA_REPOSITORY || 'BackstageTalks/tbt-data' }}
      GH_TOKEN: ${{ secrets.TBT_DATA_GH_TOKEN }}
      RAPIDAPI_KEY: ${{ secrets.RAPIDAPI_KEY }}

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
          cache-dependency-path: api/requirements-train.txt

      - name: Install dependencies and syntax-check
        run: |
          set -euo pipefail
          python -m pip install -r api/requirements-train.txt
          python -m compileall -q api scripts

      - name: Preflight
        shell: bash
        run: |
          set -euo pipefail
          test -n "$GH_TOKEN" || { echo 'Missing TBT_DATA_GH_TOKEN'; exit 1; }
          test -n "$RAPIDAPI_KEY" || { echo 'Missing RAPIDAPI_KEY'; exit 1; }
          visibility="$(gh repo view "$TBT_DATA_REPOSITORY" --json visibility -q '.visibility')"
          test "$visibility" = "PRIVATE" || { echo 'Refusing non-private data repository'; exit 1; }

      - name: Refresh current fixtures and prediction presentation
        if: ${{ inputs.refresh_current_feed }}
        shell: bash
        run: |
          set -euo pipefail
          # Important: player-card enrichment alone can only attach current
          # rank/country/photo/profile metadata. Form LXX, surface LXX, H2H
          # point-in-time context, custom_id and tournament IDs are emitted by
          # the prediction engine. Rebuild the current candidate with this
          # release before attaching presentation assets.
          python scripts/pipeline.py refresh \
            --max-requests "${{ inputs.max_refresh_requests }}" \
            --market-odds-max-events "${{ inputs.market_odds_max_events }}" \
            --betting-day-start-hour 6

      - name: Refresh current player metadata and photos
        shell: bash
        run: |
          set -euo pipefail
          mkdir -p .cache/tbt
          ARGS=(
            --data-repository "$TBT_DATA_REPOSITORY"
            --max-players "${{ inputs.max_players }}"
            --max-photo-requests "${{ inputs.max_photo_requests }}"
            --max-fallback-ranking-requests "${{ inputs.max_fallback_ranking_requests }}"
            --max-player-detail-requests "${{ inputs.max_player_detail_requests }}"
            --max-tournament-logo-requests "${{ inputs.max_tournament_logo_requests }}"
          )
          if [[ "${{ inputs.refresh_photos }}" == "true" ]]; then ARGS+=(--refresh-photos); fi
          python scripts/enrich_player_cards.py "${ARGS[@]}" | tee .cache/tbt/player-enrichment.log

      - name: Publish summary
        shell: bash
        run: |
          python - <<'PY' >> "$GITHUB_STEP_SUMMARY"
          import json
          from pathlib import Path
          report=json.loads(Path('.cache/tbt/player-enrichment/assets/player_enrichment_report.json').read_text())
          print('## Player card enrichment')
          print('')
          print(f"- Players in current feed: **{report['players_requested']:,}**")
          print(f"- Rank available: **{report['players_with_rank']:,}**")
          print(f"- Country/flag available: **{report['players_with_country']:,}**")
          print(f"- New photos downloaded: **{report['photos_downloaded']:,}**")
          print(f"- Cached photos reused: **{report['photos_cached']:,}**")
          print(f"- Photo unavailable: **{report['photos_unavailable']:,}**")
          print(f"- Tournaments in current feed: **{report.get('tournaments_requested', 0):,}**")
          print(f"- Tournament logos downloaded: **{report.get('tournament_logos_downloaded', 0):,}**")
          print(f"- Tournament logos cached: **{report.get('tournament_logos_cached', 0):,}**")
          print(f"- RapidAPI requests this run: **{report['rapidapi_requests']:,}**")
          remaining=report.get('rapidapi_remaining')
          if remaining is not None:
              print(f"- Provider requests remaining: **{remaining:,}**")
          if report.get('errors'):
              print('')
              print(f"Warnings/errors recorded: **{len(report['errors'])}** (see artifact/log).")
          PY

      - uses: actions/upload-artifact@v4
        with:
          name: player-enrichment-${{ github.run_id }}
          path: |
            .cache/tbt/player-enrichment/assets/player_enrichment_report.json
            .cache/tbt/player-enrichment.log
          if-no-files-found: error
          retention-days: 14


  deploy:
    name: Deploy enriched player cards
    needs: enrich
    runs-on: ubuntu-latest
    timeout-minutes: 45
    concurrency:
      group: tbt-production-deploy
      cancel-in-progress: false
    env:
      GH_TOKEN: ${{ secrets.TBT_DATA_GH_TOKEN }}
      TBT_DATA_REPOSITORY: ${{ vars.TBT_DATA_REPOSITORY || 'BackstageTalks/tbt-data' }}

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Prepare serving feed from freshly published enrichment
        shell: bash
        run: |
          set -euo pipefail
          test -n "$GH_TOKEN" || { echo 'Missing TBT_DATA_GH_TOKEN'; exit 1; }
          python scripts/prepare_feed.py
          test -s api/data/feed.json
          python scripts/verify_presentation_feed.py api/data/feed.json --summary

      - name: Deploy enriched BlinQ feed and application
        uses: Azure/static-web-apps-deploy@v1
        with:
          azure_static_web_apps_api_token: ${{ secrets.AZURE_STATIC_WEB_APPS_API_TOKEN_AGREEABLE_SKY_011A7FE10 }}
          repo_token: ${{ secrets.GITHUB_TOKEN }}
          action: upload
          app_location: web
          api_location: api
          output_location: ''
          skip_app_build: true

      - name: Confirm deployed prediction publication
        shell: bash
        run: |
          set -euo pipefail
          python scripts/confirm_prediction_publication.py \
            --data-repository "$TBT_DATA_REPOSITORY" \
            --deployed-feed api/data/feed.json
