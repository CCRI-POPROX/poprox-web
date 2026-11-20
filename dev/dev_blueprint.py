import base64
import hashlib
import hmac
from os import environ as env
from pathlib import Path

from flask import Blueprint, render_template, request, url_for
from poprox_storage.aws import DB_ENGINE
from poprox_storage.repositories.articles import DbArticleRepository
from poprox_storage.repositories.images import DbImageRepository
from poprox_storage.repositories.newsletters import DbNewsletterRepository

from poprox_concepts.api.tracking import LoginLinkData, TrackingLinkData
from poprox_concepts.domain.newsletter import Newsletter
from util.auth import auth
from util.newsletter_preview import newsletter_preview_context

dev = Blueprint("dev", __name__, template_folder="templates", url_prefix="/dev")
HMAC_KEY = env.get("POPROX_HMAC_KEY", "defaultpoproxhmackey")

test_newsletter_file = Path(__file__).resolve().parent / "test_newsletter.json"
TEST_NEWSLETTER = test_newsletter_file.open(encoding="utf-8").read()


@dev.route("/")
def dev_home():
    return render_template("dev_home.html")


@dev.route("/login")
def dev_login():
    email = request.args["email"]
    source = request.args.get("source", "dev_page")
    subsource = request.args.get("subsource", "dev_page")
    return auth.enroll(email, source, subsource)


@dev.route("/newsletter_loader", methods=["GET"])
def newsletter_loader_get():
    return render_template("newsletter_loader.html", newsletter=TEST_NEWSLETTER)


@dev.route("/newsletter_loader", methods=["POST"])
def newsletter_loader_post():
    newsletter_json = request.form.get("newsletter")
    # XXX: ascii was killing us.
    newsletter_json = newsletter_json.encode("ascii", "ignore").decode("ascii")
    the_newsletter = Newsletter.model_validate_json(newsletter_json)
    the_newsletter.account_id = auth.get_account_id()
    the_newsletter.treatment_id = None
    the_newsletter.experience_id = None
    with DB_ENGINE.connect() as conn:
        newsletter_repo = DbNewsletterRepository(conn)
        article_repo = DbArticleRepository(conn)
        image_repo = DbImageRepository(conn)

        # insert the articles
        for impression in the_newsletter.impressions:
            # insert this article
            for image in impression.article.images:
                new_id = image_repo.store_image(image)
                if image.image_id == impression.preview_image_id:
                    impression.article.preview_image_id = new_id
                if image.image_id == impression.preview_image_id:
                    impression.preview_image_id = new_id
                image.image_id = new_id
            image_repo.store_image
            uuid = article_repo.store_article(impression.article)
            impression.article.article_id = uuid
        conn.commit()

        # insert the newsletter object
        try:
            newsletter_repo.store_newsletter(the_newsletter)
            conn.commit()
        except:  # noqa: E722
            print("WARNING -- IT DIDNT SAVE")

    return render_template(
        "newsletter_loader_post.html", url=url_for("feedback", newsletter_id=the_newsletter.newsletter_id)
    )


@dev.route("/newsletter_preview")
def newsletter_preview():
    newsletter_id = request.args.get("newsletter_id")
    account_id = request.args.get("account_id")
    disable_links = request.args.get("disable_links", "false").lower() == "true"
    remove_footer = request.args.get("remove_footer", "true").lower() != "false"

    with DB_ENGINE.connect() as conn:
        newsletter_repo = DbNewsletterRepository(conn)
        try:
            context = newsletter_preview_context(
                newsletter_repo,
                newsletter_id,
                account_id,
                disable_links=disable_links,
                remove_footer=remove_footer,
            )
        except ValueError:
            return "Invalid newsletter_id or account_id", 400

    if context is None:
        return "Newsletter not found", 404

    return render_template("newsletter_preview.html", **context)


@dev.route("/decode")
def dev_decode():
    decode_vars = {}

    input = request.args.get("input")
    decode_vars["Raw Input"] = input

    code = input.split("/")[-1]
    signature = None

    if "." in code:
        code, signature = code.split(".", 1)

    decode_vars["Token"] = code
    decode_vars["Signature"] = signature

    try:
        token_decode = base64.urlsafe_b64decode(code.encode("utf-8"))
    except:  # noqa: E722
        token_decode = "! did not decode !"
    decode_vars["Decoded"] = token_decode

    if signature:
        raw_signature = base64.urlsafe_b64decode(signature.encode("utf-8"))
        expected_signature = hmac.digest(HMAC_KEY.encode("UTF-8"), token_decode, hashlib.sha256)
        raw_signature = base64.urlsafe_b64decode(signature.encode("utf-8"))
        if hmac.compare_digest(raw_signature, expected_signature):
            decode_vars["Signature Check"] = "Pass"
        else:
            decode_vars["Signature Check"] = "Fail"

    # Special handling for tracking links and login links
    newsletter_id = None
    try:
        tracking_link = TrackingLinkData.model_validate_json(token_decode)
        newsletter_id = tracking_link.newsletter_id
    except:  # noqa: E722
        tracking_link = None

    try:
        login_link = LoginLinkData.model_validate_json(token_decode)
        newsletter_id = login_link.newsletter_id
    except:  # noqa: E722
        login_link = None

    # If a newsletter exists...
    if newsletter_id is not None:
        decode_vars["Newsletter Id"] = newsletter_id
    newsletter = None

    with DB_ENGINE.connect() as conn:
        newsletter_repo = DbNewsletterRepository(conn)
        image_repo = DbImageRepository(conn)
        newsletters = newsletter_repo.fetch_newsletters_by_id([newsletter_id])

        if len(newsletters) > 0:
            decode_vars["Tried to find Newsletter"] = "dump shown below"
            newsletter = newsletters[0]

            for impression in newsletter.impressions:
                impression.article.images = []
                image = image_repo.fetch_image_by_id(impression.preview_image_id)
                impression.article.images.append(image)
                impression.article.preview_image_id = impression.preview_image_id

            newsletter = newsletter.model_dump_json(indent=2)
        else:
            decode_vars["Tried to find Newsletter"] = "But I couldn't"

    return render_template("dev_decode.html", decode_vars=decode_vars, newsletter=newsletter)
