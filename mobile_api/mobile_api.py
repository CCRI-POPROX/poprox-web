from datetime import datetime, timezone
from os import environ as env
from uuid import UUID

from flask import Blueprint, jsonify, request, session
from poprox_storage.repositories.clicks import DbClicksRepository
from poprox_storage.repositories.images import DbImageRepository
from poprox_storage.repositories.newsletters import DbNewsletterRepository
from sqlalchemy import select

from poprox_concepts.api.tracking import LoginLinkData, SignUpLinkData, from_hashed_base64, to_hashed_base64
from poprox_concepts.domain import Account, Article
from util.auth import auth
from util.postgres_db import DB_ENGINE, create_token, get_account, get_account_by_email, get_token

HMAC_KEY = env.get("POPROX_HMAC_KEY", "defaultpoproxhmackey")

# Blueprint for mobile API routes
mobile_api = Blueprint("mobile_api", __name__, url_prefix="/api")


@mobile_api.route("/send_enroll_token", methods=["POST"])
def send_enroll_token_api():
    email = request.json.get("email")
    source = request.json.get("source", "mobile")
    subsource = request.json.get("subsource", "app")
    if not email:
        return jsonify({"error": "Email is required"}), 400
    try:
        # Verify if account exists and is enrolled
        account = get_account_by_email(email)
        if not account:
            return jsonify({"error": "Account not found. Please sign up via web."}), 400
        if account["status"] != "onboarding_done":
            return jsonify({"error": "Account not fully enrolled. Complete onboarding via web."}), 400
        token = create_token()
        link_data = SignUpLinkData(
            email=email,
            source=source,
            subsource=subsource,
            created_at=datetime.now(timezone.utc).astimezone(),
            token_id=token.token_id,
        )
        link_data_raw = to_hashed_base64(link_data, HMAC_KEY)
        auth.send_enroll_token(source, subsource, email)
        return jsonify({"message": "Token sent successfully", "link_data_raw": link_data_raw}), 200
    except Exception:
        return jsonify({"error": "Internal server error"}), 500


@mobile_api.route("/enroll_with_token", methods=["POST"])
def enroll_with_token_api():
    link_data_raw = request.json.get("link_data_raw")
    user_code = request.json.get("code")
    try:
        link_data = from_hashed_base64(link_data_raw, HMAC_KEY, SignUpLinkData)
        token = get_token(link_data.token_id)
        if not token or token.code != user_code:
            return jsonify({"error": "Invalid or expired code"}), 400
        # Verify and enroll the user
        account = get_account_by_email(link_data.email)
        if not account:
            return jsonify({"error": "Account not found. Please sign up via web."}), 400
        if account["status"] != "onboarding_done":
            return jsonify({"error": "Please complete onboarding via web before logging in."}), 400
        auth.login_via_account_id(account["account_id"])
        login_data = LoginLinkData(account_id=account["account_id"], endpoint="home", data={})
        session["account"] = get_account(account["account_id"])
        return jsonify(
            {
                "message": "Login successful",
                "account_id": str(account["account_id"]),
                "auth_token": to_hashed_base64(login_data, HMAC_KEY),
            }
        ), 200
    except ValueError:
        return jsonify({"error": "Invalid link data format"}), 400
    except Exception:
        return jsonify({"error": "Internal server error"}), 500


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
        newsletters = newsletter_repo.fetch_newsletters_since(days_ago=1, accounts=accounts)  # Changed to 1 day
        # Take only the latest newsletter
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
        # No commit since this is read-only
        return jsonify({"newsletters": result}), 200


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
        return jsonify({"message": "Click recorded successfully"}), 200
    except Exception:
        return jsonify({"error": "Internal server error"}), 500


@mobile_api.route("/feedback", methods=["POST"])
@auth.requires_login
def submit_feedback():
    try:
        account_id = auth.get_account_id()  # noqa: F841
        impression_id = request.json.get("impression_id")
        if not impression_id:
            return jsonify({"error": "Impression ID is required"}), 400
        feedback_type = request.json.get("feedback_type")  # "positive" or "negative"
        if feedback_type not in ["positive", "negative"]:
            return jsonify({"error": "Feedback must be 'positive' or 'negative'"}), 400
        # Map positive -> True, negative -> False
        is_positive = True if feedback_type == "positive" else False
        with DB_ENGINE.connect() as conn:
            newsletter_repo = DbNewsletterRepository(conn)
            newsletter_repo.store_impression_feedback(impression_id=UUID(impression_id), is_positive=is_positive)
            conn.commit()
        return jsonify({"message": "Feedback recorded successfully"}), 200
    except ValueError:
        return jsonify({"error": "Invalid impression ID format"}), 400
    except Exception:
        return jsonify({"error": "Internal server error"}), 500


@mobile_api.route("/logout", methods=["POST"])
@auth.requires_login
def logout():
    try:
        auth.logout()  # Reuse auth.logout function
        return jsonify({"message": "Logged out successfully"}), 200
    except Exception:
        return jsonify({"error": "Internal server error"}), 500
