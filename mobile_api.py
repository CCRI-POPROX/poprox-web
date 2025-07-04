import logging
from datetime import datetime, timezone
from uuid import UUID

from flask import Blueprint, request, session
from poprox_platform.auth import auth
from poprox_platform.tracking import LoginLinkData, SignUpLinkData, from_hashed_base64, to_hashed_base64
from poprox_storage.repositories.accounts import DbAccountRepository
from poprox_storage.repositories.clicks import DbClicksRepository
from poprox_storage.repositories.images import DbImageRepository
from poprox_storage.repositories.newsletters import DbNewsletterRepository
from sqlalchemy import select

from poprox_concepts.domain import Account, Article
from util.postgres_db import DB_ENGINE, create_token, get_account, get_token

logger = logging.getLogger(__name__)

# Blueprint for mobile API routes
mobile_api = Blueprint("mobile_api", __name__, url_prefix="/api")


@mobile_api.route("/send_enroll_token", methods=["POST"])
def send_enroll_token_api():
    email = request.json.get("email")
    source = request.json.get("source", "mobile")
    subsource = request.json.get("subsource", "app")
    if not email:
        return {"error": "Email is required"}, 400
    try:
        token = create_token()
        link_data = SignUpLinkData(
            email=email,
            source=source,
            subsource=subsource,
            created_at=datetime.now(timezone.utc).astimezone(),
            token_id=token.token_id,
        )
        link_data_raw = to_hashed_base64(link_data, auth.HMAC_KEY)
        auth.send_enroll_token(source, subsource, email)
        return {"message": "Token sent successfully", "link_data_raw": link_data_raw}, 200
    except Exception as e:
        return {"error": str(e)}, 500


@mobile_api.route("/enroll_with_token", methods=["POST"])
def enroll_with_token_api():
    link_data_raw = request.json.get("link_data_raw")
    user_code = request.json.get("code")
    try:
        link_data = from_hashed_base64(link_data_raw, auth.HMAC_KEY, SignUpLinkData)
        token = get_token(link_data.token_id)
        if token and token.code == user_code:
            account_id = auth.enroll(link_data.email, link_data.source, link_data.subsource)
            login_data = LoginLinkData(account_id=account_id, endpoint="home", data={})
            session["account"] = get_account(account_id)
            return {
                "message": "Enrollment successful",
                "account_id": str(account_id),
                "token": to_hashed_base64(login_data, auth.HMAC_KEY),
            }, 200
        else:
            return {"error": "Invalid or expired code"}, 400
    except ValueError as e:
        return {"error": str(e)}, 400


@mobile_api.route("/newsletters", methods=["GET"])
@auth.requires_login
def get_newsletters():
    def fetch_images(image_repo: DbImageRepository, articles: list[Article]) -> dict:
        # Fetch image URLs for articles' preview_image_id values.
        image_ids = [article.preview_image_id for article in articles if article.preview_image_id]
        if not image_ids:
            return {}

        images_table = image_repo.tables.get("images")
        if not images_table:
            return {}

        query = select(images_table.c.image_id, images_table.c.url).where(images_table.c.image_id.in_(image_ids))
        result = image_repo.conn.execute(query).fetchall()

        return {str(row.image_id): {"url": row.url} for row in result}

    account_id = auth.get_account_id()
    with DB_ENGINE.connect() as conn:
        newsletter_repo = DbNewsletterRepository(conn)
        image_repo = DbImageRepository(conn)
        accounts = [Account(account_id=account_id)]
        newsletters = newsletter_repo.fetch_newsletters_since(days_ago=30, accounts=accounts)
        # Filter to get only the latest newsletter
        if newsletters:
            newsletters = [max(newsletters, key=lambda n: n.created_at)]
        result = []
        for newsletter in newsletters:
            impressions = newsletter_repo.fetch_impressions_by_newsletter_ids([newsletter.newsletter_id])
            images = fetch_images(image_repo, [imp.article for imp in impressions])
            articles = []
            for imp in impressions:
                article_data = {
                    "article_id": str(imp.article.article_id),
                    "impression_id": str(imp.impression_id),  # Needed for feedback
                    "headline": imp.headline,
                    "subhead": imp.subhead,
                    "url": imp.article.url,
                    "preview_image": images.get(str(imp.article.preview_image_id), {}).get("url")
                    if imp.article.preview_image_id
                    else None,
                    "position": imp.position,
                }
                articles.append(article_data)
            result.append(
                {
                    "newsletter_id": str(newsletter.newsletter_id),
                    "subject": newsletter.subject,
                    "created_at": newsletter.created_at.isoformat(),
                    "articles": articles,
                }
            )
        conn.commit()
    return {"newsletters": result}, 200


@mobile_api.route("/track/click", methods=["POST"])
@auth.requires_login
def track_click():
    try:
        account_id = auth.get_account_id()
        newsletter_id = request.json.get("newsletter_id")
        article_id = request.json.get("article_id")
        headers = {k: v for k, v in request.headers.items()}
        with DB_ENGINE.connect() as conn:
            click_repo = DbClicksRepository(conn)
            click_repo.store_click(newsletter_id, account_id, article_id, headers)
            conn.commit()
        return {"message": "Click recorded successfully"}, 200
    except Exception as e:
        return {"error": str(e)}, 400


@mobile_api.route("/feedback", methods=["POST"])
@auth.requires_login
def submit_feedback():
    try:
        account_id = auth.get_account_id()
        impression_id = request.json.get("impression_id")
        feedback_type = request.json.get("feedback_type")  # "positive" or "negative"
        if feedback_type not in ["positive", "negative"]:
            return {"error": "Feedback must be 'positive' or 'negative'"}, 400
        # Map positive -> True, negative -> False
        is_positive = True if feedback_type == "positive" else False
        with DB_ENGINE.connect() as conn:
            newsletter_repo = DbNewsletterRepository(conn)
            newsletter_repo.store_impression_feedback(impression_id=UUID(impression_id), is_positive=is_positive)
            conn.commit()
        return {"message": "Feedback recorded successfully"}, 200
    except Exception as e:
        return {"error": str(e)}, 400


@mobile_api.route("/logout", methods=["POST"])
@auth.requires_login
def logout():
    try:
        session.pop("account", None)  # Clear session data
        return {"message": "Logged out successfully"}, 200
    except Exception as e:
        logger.error(f"Error during logout: {e}")
        return {"error": str(e)}, 500
