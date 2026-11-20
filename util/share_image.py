from functools import lru_cache

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

CARD_WIDTH = 1200
CARD_HEIGHT = 630


def clean_for_share(html: str) -> str:
    """Strip footer, feedback block, and link targets from newsletter HTML before rendering."""
    soup = BeautifulSoup(html, "html.parser")

    for div in soup.find_all("div", class_="footer"):
        div.decompose()

    for div in soup.find_all("div", class_="newsletter_feedback"):
        div.decompose()

    for link in soup.find_all("a"):
        if "href" in link.attrs:
            del link.attrs["href"]

    return str(soup)


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