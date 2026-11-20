from functools import lru_cache

from playwright.sync_api import sync_playwright

CARD_WIDTH = 1200
CARD_HEIGHT = 630

@lru_cache(maxsize=32)
def render_share_image(html: str) -> bytes:
    """Render an HTML string to a 1200x630 PNG and return the bytes."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": CARD_WIDTH, "height": CARD_HEIGHT})
            page.set_content(html, wait_until="networkidle")
            return page.screenshot(type="png")
        finally:
            browser.close()