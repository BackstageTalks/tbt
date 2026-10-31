"""Real Chromium color and screenshot gate for the mobile predictions pilot.

Uses deterministic example matches and no live API or membership mutation.
"""
import os
from pathlib import Path

from playwright.sync_api import sync_playwright
from browser_mobile_projection_cards import SETUP
from browser_runtime_r43 import ORIGIN, browser_path, static_route

EXPECTED = {
    'card': 'rgb(16, 25, 28)',
    'stroke': 'rgb(43, 56, 57)',
    'copy': 'rgb(236, 243, 239)',
    'mint': 'rgb(101, 205, 164)',
    'inset': 'rgb(27, 42, 41)',
}

VALUES = """() => {
  const get = selector => {
    const node = document.querySelector(selector);
    if (!node) throw Error('Missing element: '+selector);
    const css = getComputedStyle(node);
    return {bg: css.backgroundColor, border: css.borderTopColor, color: css.color, shadow: css.boxShadow};
  };
  return {
    card: get('#dailyHubBody tr'),
    pick: get('#dailyHubBody .hub-pick-stack strong'),
    confidence: get('#dailyHubBody .hub-confidence strong'),
    detail: get('#dailyHubBody .hub-detail:not(.is-locked)'),
    projection: get('#dailyHubBody tr td:nth-child(7)'),
  };
}"""


def test_graphite():
    output = Path(os.environ.get('BLINQ_SCREENSHOTS', '/tmp/blinq-graphite-screenshots'))
    with sync_playwright() as pw:
        exe = browser_path()
        browser = pw.chromium.launch(headless=True, executable_path=exe) if exe else pw.chromium.launch(headless=True)
        try:
            for width in (320, 390, 600, 768):
                context = browser.new_context(viewport={'width': width, 'height': 844}, is_mobile=True, has_touch=True)
                page = context.new_page()
                page.route('**/*', static_route)
                page.goto(ORIGIN + '/index.html?lang=sk', wait_until='networkidle')
                for market in ('daily', 'double_faults'):
                    page.evaluate(SETUP, market)
                    values = page.evaluate(VALUES)
                    if width <= 600:
                        assert values['card']['bg'] == EXPECTED['card'], (width, market, values)
                        assert values['card']['border'] == EXPECTED['stroke'], (width, market, values)
                        assert values['card']['shadow'] == 'none', (width, market, values)
                        assert values['pick']['color'] == EXPECTED['copy'], (width, market, values)
                        assert values['confidence']['color'] == EXPECTED['mint'], (width, market, values)
                        assert values['detail']['bg'] == EXPECTED['inset'], (width, market, values)
                        if market == 'double_faults':
                            assert values['projection']['bg'] == EXPECTED['inset'], (width, market, values)
                        if width == 390:
                            output.mkdir(parents=True, exist_ok=True)
                            page.locator('#dailyHub').screenshot(
                                path=str(output / f'premium-graphite-predictions-{market}-390.png'),
                                animations='disabled',
                            )
                    else:
                        assert values['card']['bg'] != EXPECTED['card'], ('tablet unintentionally themed', values)
                context.close()
        finally:
            browser.close()
    print('Premium Graphite Chromium colors: 320/390/600px PASS; tablet unchanged; screenshots saved')


if __name__ == '__main__':
    test_graphite()
