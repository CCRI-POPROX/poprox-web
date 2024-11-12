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

from auth import Auth
from db.postgres_db import DB_ENGINE, finish_consent, finish_onboarding, finish_topic_selection
from poprox_concepts.api.tracking import LoginLinkData, SignUpToken
from poprox_concepts.domain import AccountInterest
from poprox_concepts.domain.demographics import EDUCATION_OPTIONS, GENDER_OPTIONS, RACE_OPTIONS, Demographics
from poprox_concepts.domain.topics import GENERAL_TOPICS
from poprox_concepts.internals import from_hashed_base64

DEFAULT_RECS_ENDPOINT_URL = env.get("POPROX_DEFAULT_RECS_ENDPOINT_URL")
DEFAULT_SOURCE = "website"
URL_PREFIX = env.get("URL_PREFIX", "/")

app = Flask(__name__)
app.secret_key = env.get("APP_SECRET_KEY")
HMAC_KEY = env.get("POPROX_HMAC_KEY")

ENROLL_TOKEN_TIMEOUT = timedelta(days=1)

auth = Auth(app)


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
        conn.commit()

    return redirect(url_for("home", error_desctiption="You have been opted out of experiments"))


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
        if main_menu == "unsubscribe-from-poprox" and sub_menu == "remove-email":
            account_repo.remove_subscription_for_account(auth.get_account_id())
            account_repo.end_consent_for_account(auth.get_account_id())
            account_repo.remove_email_for_account(auth.get_account_id())
            error_description = "You have been unsubscribed from POPROX."
        elif main_menu == "unsubscribe-from-poprox" and sub_menu == "remove-all-data":
            account_repo.remove_subscription_for_account(auth.get_account_id())
            account_repo.end_consent_for_account(auth.get_account_id())
            account_repo.remove_email_for_account(auth.get_account_id())
            account_repo.set_deletion_for_account(auth.get_account_id())
            error_description = "Your request has been recorded."
        elif main_menu == "return-to-standard":
            error_description = "Tell us why you're changing from the current varient in a survey sent to your email. You will be switched to the standard varient of newletters."
            # send survey -- todo
            return redirect(url_for("opt_out_of_experiments"))
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


@app.route(f"{URL_PREFIX}/")
@app.route(f"{URL_PREFIX}")
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
    if auth.get_account_status() != "pending_onboarding_survey":
        return redirect(url_for("home"))

    today = datetime.date.today()
    oneyear = timedelta(days=365)
    yearmin = (today - 123 * oneyear).year  # arbitrarilly set to 100 years old
    yearmax = (today - 18 * oneyear).year  # to ensure at least 18 year old
    yearopts = [str(year) for year in range(yearmin, yearmax)[::-1]]
    yearopts = ["Prefer not to say"] + yearopts

    if request.method == "POST":
        with DB_ENGINE.connect() as conn:
            repo = DbDemographicsRepository(conn)
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

            gender = validate(request.form.get("gender"), GENDER_OPTIONS)
            birthyear = validate(request.form.get("birthyear"), yearopts)
            education = validate(request.form.get("education"), EDUCATION_OPTIONS)
            zip5 = request.form.get("zip")
            race = validate(request.form.get("race"), RACE_OPTIONS)

            if all([gender, birthyear, education, zip5, race]):  # None is falsy
                demo = Demographics(
                    account_id=account_id,
                    gender=gender,
                    birth_year=int(birthyear),
                    zip5=zip5,
                    education=education,
                    race=";".join(race),
                )

                repo.store_demographics(demo)
                conn.commit()

                if auth.get_account_status() == "pending_onboarding_survey":
                    finish_onboarding(account_id)
                    enqueue_newsletter_request(
                        account_id=account_id,
                        profile_id=account_id,
                        group_id=None,
                        recommender_url=DEFAULT_RECS_ENDPOINT_URL,
                    )
                    return redirect(url_for("home", error_description="You have been subscribed!"))

    return render_template(
        "demographics_survey_form.html",
        genderopts=GENDER_OPTIONS,
        yearopts=yearopts,
        edlevelopts=EDUCATION_OPTIONS,
        raceopts=RACE_OPTIONS,
        auth=auth,
    )


if __name__ == "__main__":
    app.run(debug=True)
