# ruff: noqa: E402
from os import environ as env

import sqlalchemy
from dotenv import find_dotenv, load_dotenv
from flask import Flask, redirect, render_template, request, url_for
from sqlalchemy import MetaData, Table, func

ENV_FILE = find_dotenv()
if ENV_FILE:
    load_dotenv(ENV_FILE)

from poprox_storage.repositories.account_interest_log import (
    DbAccountInterestRepository,
)
from poprox_storage.repositories.accounts import DbAccountRepository

from auth import Auth
from db.postgres_db import (
    DB_ENGINE,
    finish_consent,
    finish_email_verification,
    finish_onboarding,
)
from poprox_concepts.api.tracking import LoginLinkData
from poprox_concepts.domain import AccountInterest
from poprox_concepts.domain.topics import GENERAL_TOPICS
from poprox_concepts.internals import (
    UnsubscribeLinkData,
    from_hashed_base64,
)

DEFAULT_SOURCE = "website"
URL_PREFIX = env.get("URL_PREFIX", "/")

app = Flask(__name__)
app.secret_key = env.get("APP_SECRET_KEY")
HMAC_KEY = env.get("POPROX_HMAC_KEY")

auth = Auth(app)


@app.route(f"{URL_PREFIX}/email_redirect/<path>")
def email_Redirect(path):
    data: LoginLinkData = from_hashed_base64(path, HMAC_KEY, LoginLinkData)
    auth.login_via_account_id(data.account_id)
    # TODO -- log the click.
    return redirect(url_for(data.endpoint, values=data.data))


@app.route(f"{URL_PREFIX}/login")
def login():
    return auth.login()


@app.route(f"{URL_PREFIX}/register")
def register():
    return auth.register(request.args.get("source", DEFAULT_SOURCE))


@app.route(f"{URL_PREFIX}/callback", methods=["GET", "POST"])
def callback():
    # should only be passed from special registration URLS
    source = request.args.get("source", DEFAULT_SOURCE)
    error = request.args.get("error")
    error_description = request.args.get("error_description")
    if error is not None and error == "access_denied":
        return redirect(url_for("logout", error_description=error_description))
    return auth.callback(source)


@app.route(f"{URL_PREFIX}/logout")
def logout():
    error_description = request.args.get("error_description")
    return redirect(auth.logout(error_description))


@app.route(f"{URL_PREFIX}/unsubscribe")
@auth.requires_login
def unsubscribe():
    account_id = auth.get_account_id()
    with DB_ENGINE.connect() as conn:
        account_repo = DbAccountRepository(conn)
        account_repo.end_subscription_for_account(account_id)
        conn.commit()

    return redirect(url_for("home", error_description="Sorry to see you go. You have been unsubscribed"))


@app.route(f"{URL_PREFIX}/email_unsubscribe/<path>")
def email_unsubscribe(path):
    data = from_hashed_base64(path, HMAC_KEY, UnsubscribeLinkData)
    # TODO -- log the newsletter_id from data.
    auth.login_via_account_id(data.account_id)
    with DB_ENGINE.connect() as conn:
        account_repo = DbAccountRepository(conn)
        account_repo.end_subscription_for_account(data.account_id)
        conn.commit()
    return redirect(url_for("home", error_description="Sorry to see you go. You have been unsubscribed"))


@app.route(f"{URL_PREFIX}/subscribe")
@auth.requires_login
def subscribe():
    account_id = auth.get_account_id()
    with DB_ENGINE.connect() as conn:
        account_repo = DbAccountRepository(conn)
        account_repo.create_subscription_for_account(account_id)
        conn.commit()

    return redirect(url_for("home", error_description="You have been subscribed!"))


@app.route(f"{URL_PREFIX}/consent1")
@auth.requires_login_ignore_status
def consent1():
    if auth.get_account_status() == "new_account":
        error = request.args.get("error")
        missing = request.args.get("disagree")
        if missing is None:
            # this is so we can highlight the missing consent sections
            # however, this should not happen since you cannot submit the form
            # without agreeing to all sections
            missing = []

        return render_template("consent1.html", error=error, missing=missing, auth=auth)
    else:
        # User may be in the wrong part of the workflow -- most commonly this
        # is caused by the email which sends you here. go to the "next step"
        # and let it redirect to home if that's wrong.
        return redirect(url_for("await_email_verification"))


@app.route(f"{URL_PREFIX}/consent2")
@auth.requires_login_ignore_status
def consent2():
    if auth.get_account_status() != "new_account":
        return redirect(url_for("home"))

    agrees = ["agree1", "agree2", "agree3", "agree4", "agree5"]
    agrees = [request.args.get(agree) for agree in agrees]
    if not all(agrees):
        disagree = [agree for agree in agrees if not agree]
        return redirect(
            url_for(
                "consent1",
                error="You need to agree to every section.",
                disagree=disagree,
            )
        )

    else:
        finish_consent(auth.get_account_id(), "poprox_main_consent_v1")
        return redirect(url_for("await_email_verification"))


@app.route(f"{URL_PREFIX}/email_check")
@auth.requires_login_ignore_status
def await_email_verification():
    if auth.get_account_status() not in [
        "waiting_email_verification",
        "pending_initial_preferences",
    ]:
        return redirect(url_for("home"))
    elif auth.fetch_is_email_verified():
        finish_email_verification(auth.get_account_id())
        return redirect(url_for("topics", referrer="email_check"))
    else:
        return render_template("await_email_verification.html", auth=auth)


@app.route(f"{URL_PREFIX}/")
@app.route(f"{URL_PREFIX}")
def home():
    error = request.args.get("error_description")

    metadata = MetaData()
    article_table = Table("articles", metadata, autoload_with=DB_ENGINE)
    query = (
        sqlalchemy.select(article_table.c.title, article_table.c.url, article_table.c.content)
        .order_by(func.random())
        .limit(1)
    )
    with DB_ENGINE.connect() as conn:
        result = conn.execute(query).fetchone()
        account_repo = DbAccountRepository(conn)

        is_subscribed = False
        if auth.is_logged_in():
            subscription = account_repo.fetch_subscription_for_account(auth.get_account_id())
            is_subscribed = subscription is not None

        return render_template(
            "home.html",
            article=result,
            auth=auth,
            error=error,
            is_subscribed=is_subscribed,
        )


@app.route(f"{URL_PREFIX}/topics", methods=["GET", "POST"])
@auth.requires_login
def topics():
    interest_lvls = [
        ("Very interested", 5),
        ("Interested", 4),
        ("Somewhat interested", 3),
        ("Not particularly interested", 2),
        ("Not at all interested", 1),
    ]

    def get_pref(topic):
        pref_score = request.form.get(topic.replace(" ", "_") + "_pref", None)
        if pref_score:
            return int(pref_score)
        else:
            return None

    updated = False
    onboarding = False
    if request.method == "POST":
        with DB_ENGINE.connect() as conn:
            repo = DbAccountInterestRepository(conn)
            account_id = auth.get_account_id()
            topic_prefs = []
            onboarding = request.form.get("onboarding")
            for topic in GENERAL_TOPICS:
                entity_id = repo.lookup_entity_by_name(topic)
                if entity_id is None:
                    continue
                score = get_pref(topic)
                if score is not None:
                    topic_prefs.append(
                        AccountInterest(
                            account_id=account_id,
                            entity_id=entity_id,
                            entity_name=topic,
                            preference=score,
                            frequency=None,
                        )
                    )

            repo.insert_topic_preferences(account_id, topic_prefs)
            conn.commit()
            updated = True

            if onboarding:
                finish_onboarding(auth.get_account_id())
                return redirect(url_for("home", error_description="You have been subscribed!"))

    referrer = request.args.get("referrer")
    if (referrer is not None) and (referrer == "email_check"):
        onboarding = True

    return render_template(
        "topics.html",
        updated=updated,
        onboarding=onboarding,
        topics=GENERAL_TOPICS,
        intlvls=interest_lvls,
        auth=auth,
    )


if __name__ == "__main__":
    app.run(debug=True)
