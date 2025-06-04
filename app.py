# ruff: noqa: E402
import datetime
from datetime import timedelta, timezone
from os import environ as env

from dotenv import find_dotenv, load_dotenv
from flask import Flask, redirect, render_template, request, url_for

ENV_FILE = find_dotenv()
if ENV_FILE:
    load_dotenv(ENV_FILE)

from poprox_platform.newsletter.assignments import enqueue_newsletter_request
from poprox_storage.repositories.account_interest_log import DbAccountInterestRepository
from poprox_storage.repositories.accounts import DbAccountRepository
from poprox_storage.repositories.demographics import DbDemographicsRepository
from poprox_storage.repositories.experiments import DbExperimentRepository
from poprox_storage.repositories.images import DbImageRepository
from poprox_storage.repositories.newsletters import DbNewsletterRepository

from admin.admin_blueprint import admin
from experimenter.experimenter_blueprint import exp
from poprox_concepts.api.tracking import LoginLinkData, SignUpToken
from poprox_concepts.domain import AccountInterest
from poprox_concepts.domain.account import COMPENSATION_CARD_OPTIONS, COMPENSATION_CHARITY_OPTIONS
from poprox_concepts.domain.demographics import (
    EDUCATION_OPTIONS,
    EMAIL_CLIENT_OPTIONS,
    GENDER_OPTIONS,
    RACE_OPTIONS,
    Demographics,
)
from poprox_concepts.domain.topics import GENERAL_TOPICS
from poprox_concepts.internals import from_hashed_base64
from static_web.blueprint import static_web
from util.auth import auth
from util.postgres_db import DB_ENGINE, finish_consent, finish_onboarding, finish_topic_selection

COMPENSATION_OPTIONS = COMPENSATION_CARD_OPTIONS + COMPENSATION_CHARITY_OPTIONS + ["Decline payment"]

DEFAULT_RECS_ENDPOINT_URL = env.get("POPROX_DEFAULT_RECS_ENDPOINT_URL")
DEFAULT_SOURCE = "website"
URL_PREFIX = env.get("URL_PREFIX", "/")

app = Flask(__name__)
app.secret_key = env.get("APP_SECRET_KEY", "defaultpoproxsecretkey")
HMAC_KEY = env.get("POPROX_HMAC_KEY", "defaultpoproxhmackey")

ENROLL_TOKEN_TIMEOUT = timedelta(days=1)

app.register_blueprint(admin)
app.register_blueprint(exp)


app.register_blueprint(static_web)


@app.route(f"{URL_PREFIX}/email_redirect/<path>")
def email_redirect(path):
    data: LoginLinkData = from_hashed_base64(path, HMAC_KEY, LoginLinkData)
    auth.login_via_account_id(data.account_id)

    with DB_ENGINE.connect() as conn:
        account_repo = DbAccountRepository(conn)
        account_repo.store_login(data)
        conn.commit()

    # redirect for deprecated endpoint.
    if data.endpoint == "email_unsubscribe":
        data.endpoint = "unsubscribe"

    return redirect(url_for(data.endpoint, **data.data))


@app.route(f"{URL_PREFIX}/enroll", methods=["GET"])
def pre_enroll_get():
    source = request.args.get("source", DEFAULT_SOURCE)
    subsource = request.args.get("subsource", DEFAULT_SOURCE)
    error = request.args.get("error")
    return render_template("pre_enroll.html", source=source, subsource=subsource, error=error)


@app.route(f"{URL_PREFIX}/enroll", methods=["POST"])
def pre_enroll_post():
    source = request.form.get("source", DEFAULT_SOURCE)
    subsource = request.form.get("subsource", DEFAULT_SOURCE)
    legal_age = request.form.get("legal_age")
    us_area = request.form.get("us_area")
    email = request.form.get("email")
    if (not legal_age) or (not us_area) or (not email):
        return render_template("pre_enroll.html", source=source, subsource=subsource)
    else:
        auth.send_enroll_token(source, subsource, email)
        return render_template("pre_enroll_sent.html")


@app.route(f"{URL_PREFIX}/enroll/<token_raw>", methods=["GET"])
def enroll_with_token(token_raw):
    try:
        token: SignUpToken = from_hashed_base64(token_raw, HMAC_KEY, SignUpToken)
    except ValueError:
        return redirect(
            url_for(
                "pre_enroll_post",
                error="The enrollment link you used was invalid. Please request a new enrollment link below.",
            )
        )
    now = datetime.datetime.now(timezone.utc).astimezone()
    if (not token) or (now - token.created_at > ENROLL_TOKEN_TIMEOUT):
        return redirect(
            url_for(
                "pre_enroll_post",
                source=token.source,
                subsource=token.subsource,
                error="The enrollment link you used was expired. Please request a new enrollment link below.",
            )
        )
    else:
        return auth.enroll(token.email, token.source, token.subsource)


@app.route(f"{URL_PREFIX}/logout")
def logout():
    error_description = request.args.get("error_description")
    auth.logout(error_description)
    return redirect(url_for("home"))


@app.route(f"{URL_PREFIX}/opt_out_of_experiments")
@auth.requires_login
def opt_out_of_experiments():
    account_id = auth.get_account_id()
    with DB_ENGINE.connect() as conn:
        experiment_repo = DbExperimentRepository(conn)
        experiment_repo.update_expt_assignment_to_opt_out(account_id)

        account_repo = DbAccountRepository(conn)
        account_repo.set_placebo_id(account_id)

        conn.commit()

    return redirect(
        url_for("home", error_description="You have been opted out of any experiments you were participating in.")
    )


@app.route(f"{URL_PREFIX}/unsubscribe")
@auth.requires_login
def unsubscribe():
    return render_template("pre_unsubscribe.html")


@app.route(f"{URL_PREFIX}/pre_unsubscribe", methods=["POST"])
@auth.requires_login
def pre_unsubscribe():
    main_menu = request.form.get("main-menu")
    sub_menu = request.form.get("sub-menu")
    with DB_ENGINE.connect() as conn:
        account_repo = DbAccountRepository(conn)
        if main_menu == "unsubscribe-from-poprox" and sub_menu == "unsubscribe-without-any-removal":
            account_repo.remove_subscription_for_account(auth.get_account_id())
            account_repo.end_consent_for_account(auth.get_account_id())
            error_description = "You have been unsubscribed from POPROX."
        elif main_menu == "unsubscribe-from-poprox" and sub_menu == "remove-email":
            account_repo.remove_subscription_for_account(auth.get_account_id())
            account_repo.end_consent_for_account(auth.get_account_id())
            account_repo.remove_email_for_account(auth.get_account_id())
            error_description = "You have been unsubscribed from POPROX along with removing your email from our system."
        elif main_menu == "unsubscribe-from-poprox" and sub_menu == "remove-all-data":
            account_repo.remove_subscription_for_account(auth.get_account_id())
            account_repo.end_consent_for_account(auth.get_account_id())
            account_repo.remove_email_for_account(auth.get_account_id())
            account_repo.set_deletion_for_account(auth.get_account_id())
            error_description = "Your request has been recorded."
        elif main_menu == "return-to-standard":
            error_description = "Tell us why you're changing from the current varient in a survey sent to your email.\
                You will be switched to the standard varient of newletters."
            # send survey -- todo
            return redirect(url_for("opt_out_of_experiments"))
        conn.commit()
    return render_template(("post_unsubscribe.html"), error=error_description)


@app.route(f"{URL_PREFIX}/subscribe")
@auth.requires_login
def subscribe():
    account_id = auth.get_account_id()
    with DB_ENGINE.connect() as conn:
        account_repo = DbAccountRepository(conn)
        account_repo.store_subscription_for_account(account_id)
        conn.commit()

    return redirect(url_for("home", error_description="You have been subscribed!"))


@app.route(f"{URL_PREFIX}/consent1")
@auth.requires_login
def consent1():
    error = request.args.get("error")
    missing = request.args.get("disagree")
    if missing is None:
        # this is so we can highlight the missing consent sections
        # however, this should not happen since you cannot submit the form
        # without agreeing to all sections
        missing = []

    return render_template("consent1.html", error=error, missing=missing, auth=auth)


@app.route(f"{URL_PREFIX}/consent2")
@auth.requires_login_ignore_status  # part of new_account workflow.
def consent2():
    if auth.get_account_status() != "new_account":
        return redirect(url_for("home"))

    agrees = ["agree1", "agree2", "agree3", "agree4", "agree5", "agree6", "agree7", "agree8"]
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
        finish_consent(auth.get_account_id(), "poprox_main_consent_v2")
        auth.send_post_consent()
        return redirect(url_for("topics"))


@app.route(f"{URL_PREFIX}/user_home")
@auth.requires_login
def home():
    error = request.args.get("error_description")
    with DB_ENGINE.connect() as conn:
        account_repo = DbAccountRepository(conn)

        is_subscribed = False
        if auth.is_logged_in():
            subscription = account_repo.fetch_subscription_for_account(auth.get_account_id())
            is_subscribed = subscription is not None

        return render_template(
            "home.html",
            auth=auth,
            error=error,
            is_subscribed=is_subscribed,
        )


@app.route(f"{URL_PREFIX}/feedback", methods=["GET", "POST"])
@auth.requires_login
def feedback():
    account_id = auth.get_account_id()

    def fetch_images(image_repo, recommended_articles):
        images = {}
        for article in recommended_articles:
            if article.preview_image_id:
                images[article.preview_image_id] = image_repo.fetch_image_by_id(article.preview_image_id)
        return images

    with DB_ENGINE.connect() as conn:
        newsletter_repo = DbNewsletterRepository(conn)
        image_repo = DbImageRepository(conn)

        if request.method == "POST":
            article_feedback_type = request.form.get("articlefeedbackType")
            newsletter_id = request.form.get("newsletter_id")
            impression_id = request.form.get("impression_id")

            # newsletter_id, impression_id, article_feedback_type = combined_value.split("||")

            if article_feedback_type == "positive":
                is_article_positive = True
            else:
                is_article_positive = False

            newsletter_repo.store_impression_feedback(impression_id, is_article_positive)
            impressions = newsletter_repo.fetch_impressions_by_newsletter_ids([newsletter_id])
            conn.commit()

        else:
            newsletter_id = request.args.get("newsletter_id")
            feedbackType = request.args.get("feedbackType")

            newsletter_repo.store_newsletter_feedback(account_id, newsletter_id, feedbackType)
            impressions = newsletter_repo.fetch_impressions_by_newsletter_ids([newsletter_id])
            conn.commit()

        recommended_articles = [impression.article for impression in impressions]
        images = fetch_images(image_repo, recommended_articles)

    return render_template(
        "feedback.html",
        auth=auth,
        impressions=impressions,
        images=images,
    )


@app.route(f"{URL_PREFIX}/topics", methods=["GET", "POST"])
@auth.requires_login
def topics():
    onboarding = auth.get_account_status() == "pending_initial_preferences"

    interest_lvls = [
        ("Very interested", 5),
        ("Interested", 4),
        ("Somewhat interested", 3),
        ("Not particularly interested", 2),
        ("Not at all interested", 1),
    ]

    def get_topic_preferences(account_id):  # for geting user topic preference
        with DB_ENGINE.connect() as conn:
            repo = DbAccountInterestRepository(conn)
            preferences = repo.fetch_topic_preferences(account_id)
        preferences_dict = {pref.entity_name: pref.preference for pref in preferences}
        return preferences_dict

    def get_pref(topic):
        pref_score = request.form.get(topic.replace(" ", "_") + "_pref", None)
        if pref_score:
            return int(pref_score)
        else:
            return None

    updated = False
    if request.method == "POST":
        with DB_ENGINE.connect() as conn:
            repo = DbAccountInterestRepository(conn)
            account_id = auth.get_account_id()
            topic_prefs = []
            for topic in GENERAL_TOPICS:
                entity_id = repo.fetch_entity_by_name(topic)
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

            repo.store_topic_preferences(account_id, topic_prefs)
            conn.commit()
            updated = True

            if onboarding:
                finish_topic_selection(auth.get_account_id())
                return redirect(url_for("onboarding_survey"))

        user_topic_preferences = get_topic_preferences(auth.get_account_id())

    else:  # topic get method
        user_topic_preferences = get_topic_preferences(auth.get_account_id())

    return render_template(
        "topics.html",
        updated=updated,
        onboarding=onboarding,
        topics=GENERAL_TOPICS,
        intlvls=interest_lvls,
        auth=auth,
        user_topic_preferences=user_topic_preferences,
    )


@app.route(f"{URL_PREFIX}/demographic_survey", methods=["GET", "POST"])
@auth.requires_login
def onboarding_survey():
    onboarding = auth.get_account_status() == "pending_onboarding_survey"

    today = datetime.date.today()
    oneyear = timedelta(days=365)
    yearmin = (today - 123 * oneyear).year  # arbitrarilly set to 100 years old
    yearmax = (today - 18 * oneyear).year  # to ensure at least 18 year old
    yearopts = [str(year) for year in range(yearmin, yearmax)[::-1]]
    yearopts = ["Prefer not to say"] + yearopts

    def convert_to_record(row: Demographics, zip5: str, compensation: str) -> dict:
        race_list = row.race.split(";")  # Split the race field into individual races
        predefined_races = [r for r in race_list if r in RACE_OPTIONS]
        custom_races = next((r for r in race_list if r not in RACE_OPTIONS), None)

        email_client_list = row.email_client.split(";")
        predefined_email_clients = [e for e in email_client_list if e in EMAIL_CLIENT_OPTIONS]
        custom_email_clients = next((e for e in email_client_list if e not in EMAIL_CLIENT_OPTIONS), None)
        return {
            "gender": row.gender,
            "birth_year": str(row.birth_year),
            "zip5": zip5,
            "education": row.education,
            "raw_race": row.race,
            "race": ";".join(predefined_races),  # Join predefined races back into a single string
            "race_notlisted": custom_races,
            "raw_email_client": row.email_client,
            "email_client": ";".join(predefined_email_clients),
            "email_client_other": custom_email_clients,
            "compensation": compensation,
        }

    def fetch_demographic_information(account_id):
        with DB_ENGINE.connect() as conn:
            repo = DbDemographicsRepository(conn)
            account_repo = DbAccountRepository(conn)
            demographics = repo.fetch_latest_demographics_by_account_id(account_id)
            zip5 = account_repo.fetch_zip5(account_id)
            compensation = account_repo.fetch_compensation(account_id)
        if demographics and zip5:
            combined_dict = convert_to_record(demographics, zip5, compensation)
            return combined_dict
        else:
            return None

    updated = False
    if request.method == "POST":
        with DB_ENGINE.connect() as conn:
            repo = DbDemographicsRepository(conn)
            account_repo = DbAccountRepository(conn)
            account_id = auth.get_account_id()

            def validate(val, options):
                if isinstance(val, list):
                    val = [v for v in val if v in options]
                    if len(val) == 0:
                        return None
                else:
                    if val not in options:
                        return None
                return val

            def zip_validation(zip_code):
                if zip_code:
                    if len(zip_code) == 5 and zip_code.isdigit():
                        return zip_code
                return "00000"

            gender = validate(request.form.get("gender"), GENDER_OPTIONS)
            birthyear = validate(request.form.get("birthyear"), yearopts)
            if birthyear == "Prefer not to say":
                birthyear = None
            education = validate(request.form.get("education"), EDUCATION_OPTIONS)
            zip5 = zip_validation(request.form.get("zip"))
            allrace = request.form.getlist("race")
            race = validate(allrace, RACE_OPTIONS)
            race_notlisted = None
            if "Not listed (please specify)" in race:
                race_notlisted = next((i for i in allrace if i not in RACE_OPTIONS), None)
            all_email_client = request.form.getlist("email_client")
            email_client = validate(all_email_client, EMAIL_CLIENT_OPTIONS)
            email_client_other = None
            if "Other" in email_client:
                email_client_other = next((i for i in all_email_client if i not in EMAIL_CLIENT_OPTIONS), None)

            compensation = validate(request.form.get("compensation"), COMPENSATION_OPTIONS)

            # If `race_notlisted` has a value, add it to `race`
            if race_notlisted:
                race.append(race_notlisted)

            if email_client_other:
                email_client.append(email_client_other)

            if all([gender, birthyear, education, zip5, race, email_client]):  # None is falsy
                zip5 = zip5
                demo = Demographics(
                    account_id=account_id,
                    gender=gender,
                    birth_year=int(birthyear),
                    zip3=str(zip5)[:3],
                    education=education,
                    race=";".join(race) if isinstance(race, list) else race,
                    email_client=";".join(email_client) if isinstance(email_client, list) else email_client,
                )

                repo.store_demographics(demo)
                account_repo.store_zip5(account_id, zip5)
                account_repo.store_compensation(account_id, compensation)
                conn.commit()
                updated = True
            if onboarding:
                finish_onboarding(account_id)
                enqueue_newsletter_request(
                    account_id=account_id,
                    profile_id=account_id,
                    group_id=None,
                    recommender_url=DEFAULT_RECS_ENDPOINT_URL,
                )
                return redirect(url_for("home", error_description="You have been subscribed!"))
        user_demographic_information = fetch_demographic_information(auth.get_account_id())
    else:
        user_demographic_information = fetch_demographic_information(auth.get_account_id())

    return render_template(
        "demographics_survey_form.html",
        updated=updated,
        onboarding=onboarding,
        genderopts=GENDER_OPTIONS,
        yearopts=yearopts,
        edlevelopts=EDUCATION_OPTIONS,
        raceopts=RACE_OPTIONS,
        clientopts=EMAIL_CLIENT_OPTIONS,
        giftcardopts=COMPENSATION_CARD_OPTIONS,
        donationopts=COMPENSATION_CHARITY_OPTIONS,
        auth=auth,
        user_demographic_information=user_demographic_information,
    )


if __name__ == "__main__":
    app.run(debug=True)
