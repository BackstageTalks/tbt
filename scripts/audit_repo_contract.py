#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'web'

errors: list[str] = []
checks: list[str] = []


def fail(message: str) -> None:
    errors.append(message)


def ok(message: str) -> None:
    checks.append(message)


def read(path: Path) -> str:
    if not path.is_file():
        fail(f'missing file: {path.relative_to(ROOT)}')
        return ''
    return path.read_text(encoding='utf-8')


def load_json(path: Path):
    text = read(path)
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception as exc:
        fail(f'invalid JSON {path.relative_to(ROOT)}: {exc}')
        return {}


index = read(WEB / 'index.html')
app = read(WEB / 'app.js')
auth = read(WEB / 'auth.js')
responsive = read(WEB / 'responsive.js')
css = read(WEB / 'blinq-app.css')
ui = load_json(WEB / 'ui-config.json')
release = load_json(WEB / 'release.json')
static = load_json(WEB / 'staticwebapp.config.json')
site = load_json(WEB / 'config' / 'site-content.json')
tiers = load_json(WEB / 'config' / 'membership-tiers.json')

# 1. Release/cache identity is one source of truth.
meta_release = re.search(r'<meta name="blinq-web-release" content="([^"]+)"', index)
meta_patch = re.search(r'<meta name="blinq-web-patch" content="736-r(\d+)"', index)
if not meta_release or not meta_patch:
    fail('index.html is missing release/patch meta markers')
else:
    rel = meta_release.group(1)
    patch_n = meta_patch.group(1)
    asset = str(ui.get('asset_revision', ''))
    expected_patch = f'736-r{patch_n}'
    if str(ui.get('revision')) != rel or str(ui.get('ui_revision')) != rel:
        fail('ui-config revision does not match index release')
    if str(release.get('release')) != rel or str(release.get('ui_revision')) != rel:
        fail('release.json revision does not match index release')
    if str(ui.get('ui_patch')) != expected_patch:
        fail(f'ui-config ui_patch != {expected_patch}')
    if str(release.get('patch')) != expected_patch:
        fail(f'release.json patch != {expected_patch}')
    if not asset.isdigit():
        fail('ui-config asset_revision must be numeric')
    required_refs = [
        f'/blinq-app.css?v={asset}&p={patch_n}',
        f'/auth.js?v={asset}&p={patch_n}',
        f'/responsive.js?v={asset}&p={patch_n}',
        f'/app.js?v={asset}&p={patch_n}',
        f'/assets/blinq_loading_r29.svg?v={asset}&p={patch_n}',
    ]
    for ref in required_refs:
        if ref not in index:
            fail(f'index cache reference missing/out of sync: {ref}')
    runtime_files = {'web/app.js': app, 'web/blinq-app.css': css, 'web/responsive.js': responsive}
    stale = []
    for name, text in runtime_files.items():
        for m in re.finditer(r'\?v=(\d+)&p=(\d+)', text):
            if m.group(1) != asset or m.group(2) != patch_n:
                stale.append((name, m.group(0)))
    if stale:
        fail(f'stale runtime cache references: {stale[:10]}')
    if f'BlinQ runtime patch {rel}-r{patch_n}' not in css:
        fail('CSS runtime patch marker is out of sync')
    ok(f'release identity {rel} / {expected_patch} / asset {asset}')

# 2. Auth frontend interface must be internally complete and match app usage.
fn_names = set(re.findall(r'\b(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(', auth))
var_names = set(re.findall(r'\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\b', auth))
obj = re.search(r'window\.BlinqAuth\s*=\s*\{([\s\S]*?)\n\s*\};', auth)
exports: set[str] = set()
if not obj:
    fail('window.BlinqAuth export object not found')
else:
    for raw in obj.group(1).replace('\n', ' ').split(','):
        token = raw.strip()
        if not token:
            continue
        name = token.split(':', 1)[0].strip()
        if re.fullmatch(r'[A-Za-z_$][\w$]*', name):
            exports.add(name)
    undefined = sorted(name for name in exports if name not in fn_names and name not in var_names)
    if undefined:
        fail(f'BlinqAuth exports undefined identifiers: {undefined}')
uses = set(re.findall(r'\bBlinqAuth\.([A-Za-z_$][\w$]*)', app))
missing = sorted(uses - exports)
if missing:
    fail(f'app.js calls missing BlinqAuth methods: {missing}')
for required in ('adminSaveUiConfig', 'adminUploadMedia', 'adminDiagnostics', 'adminUsers', 'feed', 'insights', 'liveRadar'):
    if required not in exports:
        fail(f'critical BlinqAuth export missing: {required}')
ok(f'frontend auth contract: {len(exports)} exports / {len(uses)} app calls')

# 3. API routes required by current frontend.
api = read(ROOT / 'api' / 'function_app.py')
required_routes = (
    'route="v1/feed"', 'route="v1/ui-config"', 'route="v1/content/news"',
    'route="v1/live-radar"', 'route="v1/insights"', 'route="v1/admin/diagnostics"',
    'route="v1/admin/users"', 'route="v1/admin/users/{user_id}/payments"',
    'route="v1/admin/audit"', 'route="v1/admin/ui-config"', 'route="v1/admin/media"',
    'route="v1/push/config"', 'route="v1/push/subscription"',
    'route="v1/internal/account-inactivity-worker"',
)
for token in required_routes:
    if token not in api:
        fail(f'backend route missing: {token}')
if '_support_request_allowed' in api or '_SUPPORT_RATE_' in api:
    fail('retired support runtime still present in API')
ok('current frontend/backend route contract present')

# 4. Retired UI/support ballast must stay retired.
retired_runtime = ('VIP_RAIL', 'VIP_TELEGRAM', 'FOOTBALL_ACCESS', 'BTTS_BONUS_PANEL', 'FOOTER_SYSTEM')
ui_blob = json.dumps(ui, ensure_ascii=False)
for token in retired_runtime:
    if token in ui_blob:
        fail(f'retired UI token remains in ui-config: {token}')
if any(key.startswith('SIDEBAR_PROMO_') for key in (ui.get('elements') or {})):
    fail('retired SIDEBAR_PROMO slots remain in ui-config')
site_blob = json.dumps(site, ensure_ascii=False).lower()
if 'blinq support' in site_blob or 'support_email' in site_blob:
    fail('retired BlinQ Support UI/contact remains in site-content')
if "['support'" in app.lower() or 'data-admin-tab="support"' in app.lower():
    fail('retired Support admin UI remains in app.js')
for token in ('renderAdminCampaigns', 'data-campaign-field', 'adminPayments', 'adminAddPayment', 'adminBannerAnalytics'):
    if token in app or token in auth:
        fail(f'retired frontend admin subsystem returned: {token}')
if 'campaigns' in ui or 'advertisers' in ui:
    fail('retired campaign/advertiser manager remains in ui-config')
ok('retired support/VIP/BTTS/sidebar/campaign admin runtime removed')

# 4b. Legacy visual systems must stay removed while current advanced controls remain.
elements = ui.get('elements') or {}
for key in ('content_rows', 'header_cta', 'creative_specs'):
    if key in ui:
        fail(f'retired visual config returned: {key}')
for key in ('show_header_feature_strip', 'snapshot_cards'):
    if key in (ui.get('dashboard') or {}):
        fail(f'retired dashboard visual config returned: {key}')
for element_id in ('PREDICTION_TOOLBAR', 'SIDEBAR_PREDICTIONS'):
    if element_id in elements:
        fail(f'dead visual access element returned: {element_id}')
if 'row_presets' in (ui.get('admin') or {}):
    fail('retired admin row preset visual config returned')
legacy_kinds = sorted(element_id for element_id, item in elements.items() if str((item or {}).get('kind')) in {'header_slot', 'large_banner'})
if legacy_kinds:
    fail(f'retired header/content banner elements returned: {legacy_kinds}')
for i in range(1, 6):
    hero_id = f'HERO_BANNER_{i}'
    hero_item = elements.get(hero_id) or {}
    if hero_item.get('kind') != 'hero_banner':
        fail(f'current hero slot missing/invalid: {hero_id}')
    if 'access' in hero_item or 'click_access' in hero_item:
        fail(f'hero membership gating returned: {hero_id}')
for token in ('headerFeatureStrip', 'bannerTop', 'bannerMid', 'bannerBottom'):
    if token in index:
        fail(f'retired visible DOM hook returned: {token}')
for token in ('function renderHeaderSlots', 'function renderBanners', 'rowPresetMap', 'data-admin-row-preset', 'data-simple-banner-state', 'data-banner-state-plan', 'data-banner-preset', 'Viditeľnosť podľa levelu'):
    if token in app:
        fail(f'retired visual/admin runtime returned: {token}')
if 'admin-row-advanced' not in app or 'data-admin-hub-row-state' not in app:
    fail('current advanced per-row prediction controls were removed during visual cleanup')
for token in ('.legacy-nav-hook', '#headerFeatureStrip', '.promo-zone', '.header-slot', '.admin-banner-workspace', '.admin-overview-v687', '.admin-console-v675', '.admin-accounts-toolbar-v669'):
    if token in css:
        fail(f'retired CSS selector returned: {token}')
banners_cfg = load_json(WEB / 'config' / 'banners.json')
if 'ads_help' in banners_cfg:
    fail('unused legacy banner editor help metadata returned')
if 'closeMenu' in responsive or 'BlinqUI.closeMenu' in app:
    fail('retired navigation drawer compatibility API returned')
ok('r23 legacy visual/header/promo/banner-tier systems removed')

# 5. Critical local assets and fallbacks.
critical_assets = [
    WEB / 'assets' / 'blinq_loading_r29.svg',
    WEB / 'assets' / 'blinq_loading_scene_v736.webp',
    WEB / 'assets' / 'blinq_logo.svg',
    WEB / 'assets' / 'missing_foto_m.webp',
    WEB / 'assets' / 'missing_foto_w.webp',
    WEB / 'assets' / 'tournament-fallbacks' / 'tennis.svg',
]
for path in critical_assets:
    if not path.is_file() or path.stat().st_size == 0:
        fail(f'critical asset missing/empty: {path.relative_to(ROOT)}')
loader = read(WEB / 'assets' / 'blinq_loading_r29.svg')
if '<animateTransform' not in loader:
    fail('loader ball animation missing')
if 'data:image/webp;base64,' in loader:
    fail('loader scene is embedded as base64 again')
for path in re.findall(r"url\(['\"]?(/assets/[^)'\"?#]+)", css):
    candidate = WEB / path.lstrip('/')
    if not candidate.is_file():
        fail(f'CSS references missing local asset: {path}')
# Verify direct static references in index resolve to shipped web files.
for ref in re.findall(r'(?:src|href)="(/[^"?#]+)', index):
    if ref.startswith('/api/'):
        continue
    candidate = WEB / ref.lstrip('/')
    if not candidate.is_file():
        fail(f'index references missing static file: {ref}')
ok('critical media/fallback assets + index static references present')

# 6. Membership/daily hub schema required by current product.
for tier in ('rookie', 'pro', 'elite', 'legend', 'goat'):
    if not isinstance(((tiers.get('tiers') or {}).get(tier) or {}).get('features'), list):
        fail(f'membership tier features missing: {tier}')
plans = ui.get('plans') or {}
if (plans.get('trial') or {}).get('enabled') is not False or int((plans.get('trial') or {}).get('trial_hours') or 0) != 0:
    fail('legacy ROOKIE trial must stay disabled')
rookie_plan = plans.get('rookie') or {}
if rookie_plan.get('enabled') is not True or rookie_plan.get('unlimited') is not True or rookie_plan.get('duration_days') is not None:
    fail('ROOKIE must stay enabled and unlimited without duration')
goat_plan = plans.get('goat') or {}
if goat_plan.get('lifetime') is not False or goat_plan.get('unlimited') is True or not isinstance(goat_plan.get('duration_days'), int) or goat_plan.get('duration_days') <= 0:
    fail('GOAT must use a finite editable default duration')
if 'applyV6514AdminCleanup();\n      const result=await BlinqAuth.adminSaveUiConfig(state.ui);' not in app:
    fail('publish must sanitize retired visual fields before saving')
for tier in ('rookie', 'pro', 'elite', 'legend', 'goat'):
    if not isinstance((plans.get(tier) or {}).get('eyebrow', ''), str):
        fail(f'membership eyebrow must remain editable text: {tier}')
inactivity = ui.get('account_inactivity') or {}
if inactivity.get('auto_expire_rookie') is not True:
    fail('ROOKIE inactivity housekeeping must mark dormant accounts EXPIRED by default')
if 'data-admin-level-field="eyebrow"' not in app or 'data-admin-inactivity-field="enabled"' not in app:
    fail('r24 membership/inactivity Admin controls missing')
hub = ((ui.get('dashboard') or {}).get('daily_hub') or {})
tabs = hub.get('tabs') or {}
for tab in ('daily', 'value', 'ace', 'doubles', 'games', 'sets'):
    if tab not in tabs:
        fail(f'daily hub tab missing: {tab}')
    elif tabs[tab].get('enabled') is False:
        fail(f'daily hub tab unexpectedly disabled: {tab}')
rookie = ((tabs.get('daily') or {}).get('plans') or {}).get('rookie') or {}
if str(rookie.get('selection_mode')) != 'stable_random' or int(rookie.get('visible_rows') or 0) != 1 or rookie.get('blur_remaining') is not True:
    fail(f'ROOKIE daily rule drifted: {rookie}')
ok('membership + daily hub core schema present')

# 7. Storage diagnostics/current support policy.
for label in ('PLAYER IMAGES', 'TOURNAMENT LOGOS', 'INFO STORAGE', 'LIVE DATA', 'ACCOUNT CHECK', 'EMAIL / SMTP'):
    if label not in app:
        fail(f'Admin System diagnostic missing: {label}')
if 'SUPPORT STORAGE' in app:
    fail('retired SUPPORT STORAGE diagnostic remains')
if 'BLINQ_STORAGE_CONNECTION_STRING' not in app:
    fail('Admin diagnostics do not surface unified storage setting')
ok('Admin System diagnostics contract present')

# 8. Deployment safety contracts.
data_yml = read(ROOT / '.github' / 'workflows' / 'data.yml')
player_yml = read(ROOT / '.github' / 'workflows' / 'player-enrichment.yml')
ci_yml = read(ROOT / '.github' / 'workflows' / 'ci.yml')
account_yml = read(ROOT / '.github' / 'workflows' / 'account-inactivity.yml')
if 'BLINQ_SKIP_STALE_DEPLOY=true' not in data_yml or 'git rev-parse origin/main' not in data_yml:
    fail('data workflow stale-deploy guard missing')
if 'ref: main' not in player_yml:
    fail('player-enrichment deploy does not checkout current main')
if 'Verify deployed frontend release' not in ci_yml:
    fail('CI production frontend verification missing')
if 'Guard fresh main commit' not in ci_yml or 'origin/main' not in ci_yml or 'STALE CI RUN' not in ci_yml:
    fail('CI stale re-run guard missing')
if 'run-name: "BlinQ CI · ${{ github.sha }}"' not in ci_yml:
    fail('CI run name does not expose commit SHA')
if 'TBT_ACCOUNT_INACTIVITY_ENABLED' not in account_yml or 'BLINQ_ACCOUNT_WORKER_TOKEN' not in account_yml or '/api/v1/internal/account-inactivity-worker' not in account_yml:
    fail('daily account inactivity workflow contract missing')
ok('workflow stale-deploy + stale-rerun + account-inactivity safeguards present')

# 9. Production tree cleanliness.
# In CI the checkout itself necessarily contains .git/.git metadata.  The audit must
# inspect files tracked by Git, not every file present in the runner workspace.
def tracked_repo_files() -> list[Path]:
    try:
        proc = subprocess.run(
            ['git', '-C', str(ROOT), 'ls-files', '-z'],
            check=True, capture_output=True, text=False,
        )
        return [ROOT / raw.decode('utf-8') for raw in proc.stdout.split(b'\0') if raw]
    except (FileNotFoundError, subprocess.CalledProcessError):
        # ZIP/local fallback: walk the shipped tree, but never treat VCS/runtime
        # metadata as a production artifact.
        out: list[Path] = []
        for candidate in ROOT.rglob('*'):
            if not candidate.is_file():
                continue
            rel = candidate.relative_to(ROOT)
            if any(part in {'.git', '.pytest_cache', '__pycache__'} for part in rel.parts):
                continue
            out.append(candidate)
        return out

for path in tracked_repo_files():
    # CI sanitizes compiled/cache artifacts before this audit. A file can still
    # be listed in Git's index when it came from an older browser-uploaded ZIP,
    # but if it no longer exists in the production working tree it cannot ship.
    if not path.exists():
        continue
    rel = path.relative_to(ROOT)
    if any(part in {'.pytest_cache', '__pycache__'} for part in rel.parts):
        fail(f'cache/build artifact committed: {rel}')
    if path.suffix in {'.pyc', '.pyo'} or path.name.endswith(('.bak', '.tmp')):
        fail(f'temporary/compiled artifact committed: {rel}')
root_legacy = sorted(p.name for p in ROOT.glob('BLINQ_*.md')) + sorted(p.name for p in ROOT.glob('AUDIT_*.md'))
if root_legacy:
    fail(f'historical release docs still clutter repository root: {root_legacy}')
ok('production tree cleanliness checks complete')

# 10. Release-specific runtime contracts that must be checked before PASS.
_admin_storage = (ROOT / "api" / "tbt" / "services" / "admin_storage.py").read_text(encoding="utf-8")
if "_normalize_membership_invariants(payload)" not in _admin_storage:
    fail("r26 membership publish self-heal is missing")

_app = app
_ui = ui
if not (((_ui.get("dashboard") or {}).get("daily_hub") or {}).get("tabs") or {}).get("prime", {}).get("enabled"):
    fail("Short Odds public configuration is missing")
if "Kopírovať nastavenie z iného levelu" in _app or "data-admin-action=\"copy-plan\"" in _app or "adminCopyFrom" in _app:
    fail("retired copy-from-level admin tool is still present")
if "admin-see-all-rule-note" in _app or "const rows=['daily','prime','value','ace','double_faults','doubles','games','sets','see_all'].map" not in _app:
    fail("unified SEE ALL controls are missing")
if "BlinQ runtime patch 7.3.6-r28 — mobile-first stability contract" not in css:
    fail("r28 final responsive stability layer is missing")
if "blinq-mobile-keyboard-open" not in responsive or "--bq-viewport-height" not in responsive:
    fail("r28 dynamic mobile viewport/keyboard handling is missing")
if "const mobileLabels=dailyHubColumns(tab);" not in _app:
    fail("r28 semantic mobile table labels are missing")
ok('r26-r29 publish, Short Odds, separate Double Faults, SEE ALL and mobile responsive contracts present')

if errors:
    print('BlinQ repository contract audit: FAIL', file=sys.stderr)
    for item in errors:
        print(f'  - {item}', file=sys.stderr)
    sys.exit(1)

print('BlinQ repository contract audit: PASS')
for item in checks:
    print(f'  ✓ {item}')
