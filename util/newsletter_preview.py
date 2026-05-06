import logging
from datetime import datetime, timezone
from uuid import UUID

from bs4 import BeautifulSoup
from sqlalchemy import and_, select
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

    return embeddable_newsletter_html(soup)


def remove_newsletter_footers(soup):
    for link in soup.find_all("a", class_="learn_more"):
        link.decompose()

    for feedback_block in soup.find_all("div", class_="newsletter_feedback"):
        feedback_block.decompose()


def embeddable_newsletter_html(soup: BeautifulSoup) -> str:
    style_tags = "".join(str(style_tag) for style_tag in soup.find_all("style"))
    body = soup.body

    if body is None:
        return str(soup)

    body_contents = "".join(str(child) for child in body.contents)
    return f"{style_tags}{body_contents}"


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
    body_html = fetch_newsletter_preview_html(newsletter_repo, parsed_newsletter_id, parsed_account_id)

    if body_html is None:
        return None

    return {
        "newsletter_html": remove_newsletter_feedback(
            body_html, disable_links=disable_links, remove_footer=remove_footer
        ),
    }


def fetch_newsletter_preview_html(
    newsletter_repo: DbNewsletterRepository,
    newsletter_id: UUID | None = None,
    account_id: UUID | None = None,
) -> str | None:
    if newsletter_id:
        newsletters_table = newsletter_repo.tables["newsletters"]
        clauses = [newsletters_table.c.newsletter_id == newsletter_id]
        if account_id:
            clauses.append(newsletters_table.c.account_id == account_id)

        query = select(newsletters_table.c.html).where(and_(*clauses)).limit(1)
        row = newsletter_repo.conn.execute(query).fetchone()
        return row.html if row else None

    if account_id:
        newsletter = newsletter_repo.fetch_most_recent_newsletter(
            account_id,
            datetime(1970, 1, 1, tzinfo=timezone.utc),
        )
        return newsletter.body_html if newsletter else None

    return None
