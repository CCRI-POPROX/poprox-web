import logging
from uuid import UUID

from bs4 import BeautifulSoup
from poprox_storage.repositories.newsletters import DbNewsletterRepository

logger = logging.getLogger(__name__)


def remove_newsletter_feedback(body: str, *, disable_links: bool = False, remove_footer: bool = True) -> str:
    soup = BeautifulSoup(body or "", "html.parser")
    remove_newsletter_footers(soup)

    if remove_footer:
        for div in soup.find_all("div", class_="footer"):
            div.decompose()

    if disable_links:
        for link in soup.find_all("a"):
            if "href" in link.attrs:
                del link.attrs["href"]
                link.attrs["title"] = "This is a preview. Links are disabled."
    else:
        for link in soup.find_all("a"):
            if "href" in link.attrs:
                link.attrs["target"] = "_blank"
                link.attrs["rel"] = "noopener noreferrer"

    return str(soup)


def remove_newsletter_footers(soup):
    for link in soup.find_all("a", class_="learn_more"):
        link.decompose()

    for feedback_block in soup.find_all("div", class_="newsletter_feedback"):
        feedback_block.decompose()


def newsletter_preview_context(
    newsletter_repo: DbNewsletterRepository,
    newsletter_id: str | UUID | None = None,
    account_id: str | UUID | None = None,
    *,
    disable_links: bool = False,
    remove_footer: bool = True,
) -> dict | None:
    parsed_newsletter_id = UUID(str(newsletter_id)) if newsletter_id else None
    parsed_account_id = UUID(str(account_id)) if account_id else None
    body_html = newsletter_repo.fetch_newsletter_preview(parsed_newsletter_id, parsed_account_id)

    if body_html is None:
        return None

    return {
        "newsletter_html": remove_newsletter_feedback(
            body_html, disable_links=disable_links, remove_footer=remove_footer
        ),
    }
