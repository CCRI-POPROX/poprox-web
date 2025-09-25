# ruff: noqa: E402

import logging
from os import environ as env

from dotenv import find_dotenv, load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, url_for

ENV_FILE = find_dotenv()
if ENV_FILE:
    load_dotenv(ENV_FILE)

from poprox_storage.aws.queues import enqueue_newsletter_request
from poprox_storage.repositories.account_interest_log import DbAccountInterestRepository
from poprox_storage.repositories.accounts import DbAccountRepository
from poprox_storage.repositories.clicks import DbClicksRepository
from poprox_storage.repositories.demographics import DbDemographicsRepository
from poprox_storage.repositories.experiments import DbExperimentRepository
from poprox_storage.repositories.images import DbImageRepository
from poprox_storage.repositories.newsletters import DbNewsletterRepository

from admin.admin_blueprint import admin
from experimenter.experimenter_blueprint import exp
from mobile_api.mobile_api import mobile_api
from poprox_concepts.api.tracking import LoginLinkData, SignUpLinkData, TrackingLinkData
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
from util.postgres_db import (
    DB_ENGINE,
    fetch_compensation_preferences,
    fetch_demographic_information,
    finish_consent,
    finish_demographic_survey,
    finish_onboarding,
    finish_topic_selection,
    get_token,
)

logger = logging.getLogger(__name__)

COMPENSATION_OPTIONS = COMPENSATION_CARD_OPTIONS + COMPENSATION_CHARITY_OPTIONS + ["Decline payment"]

DEFAULT_RECS_ENDPOINT_URL = env.get("POPROX_DEFAULT_RECS_ENDPOINT_URL")
DEFAULT_SOURCE = "website"
URL_PREFIX = env.get("URL_PREFIX", "/")

app = Flask(__name__)
app.secret_key = env.get("APP_SECRET_KEY", "defaultpoproxsecretkey")
HMAC_KEY = env.get("POPROX_HMAC_KEY", "defaultpoproxhmackey")

TOPIC_HINTS = {
    "U.S. news": "U.S. news and events, including politics, economy, \
        crime, culture, health, education, and other major national topics.",
    "World news": "Global news, covering international events, politics, \
        conflicts, trade, diplomacy, and issues affecting multiple countries.",
    "Politics": "Government and politics at all levels—local, \
        national, and international. Covers laws, leadership, elections, \
        policies, and global groups like the UN.",
    "Business": "Business, finance, markets, industries, and \
        economic activities worldwide, involving companies, governments, \
        and other organizations.",
    "Entertainment": "Movies, music, TV, books, art, and \
        entertainment, focusing on the artists and creators.",
    "Sports": "Team and individual sports at all levels, \
        including games, athletes, leagues, media, business, gear, and \
        major issues or controversies.",
    "Health": "Physical and mental health, including diseases, \
        treatments, medicine, injuries, and public health topics.",
    "Science": "Scientific discoveries, experiments, and \
        knowledge in fields like biology, space, technology, and social sciences.",
    "Technology": "Technology, including gadgets, software, \
        innovations, and digital tools, plus issues and debates around their use.",
    "Lifestyle": "Daily life, including style, hobbies, relationships, \
        travel, wellness, and personal interests.",
    "Religion": "Religion, its role in society, and \
        related social or political issues and controversies.",
    "Climate and environment": "The environment, including \
        nature, wildlife, and how human actions affect the planet, \
        plus efforts to manage and protect it.",
    "Education": "Teaching, learning, and managing schools \
        and other educational institutions.",
    "Oddities": "Weird, funny, or unusual stories that stand \
        out for being surprising or quirky.",
}


def validate(val, options):
    """Convenience method to validate select options in form request.

    Validates if an option parameter (val) in the form request is a valid option in options.

    Args:
        val (str): The option parameter to be validated.
        options (list): The list of options the parameter is to be validated against.

    Returns:
        str | None: The option parameter (val) is returned if it is valid otherwise None is returned.
    """
    if isinstance(val, list):
        val = [v for v in val if v in options]
        if len(val) == 0:
            return None
    else:
        if val not in options:
            return None
    return val


# Register Blueprints at the top
app.register_blueprint(mobile_api)
app.register_blueprint(admin)
app.register_blueprint(exp)
app.register_blueprint(static_web)


@app.context_processor
def dfault_jinja_variables():
    """returned properties here will be added to all jinja renders"""
    return dict(auth=auth)


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

    # To test a source, subsource pair with a custom template just add that to this dictionary
    templates = {}
    template = "pre_enroll.html"
    if (source, subsource) in templates:
        template = templates[(source, subsource)]

    return render_template(template, source=source, subsource=subsource, error=error)


@app.route(f"{URL_PREFIX}/subscribe", methods=["POST"])
def pre_enroll_post():
    source = request.form.get("source", DEFAULT_SOURCE)
    subsource = request.form.get("subsource", DEFAULT_SOURCE)
    legal_age = request.form.get("legal_age")
    us_area = request.form.get("us_area")
    email = request.form.get("email")
    if (not legal_age) or (not us_area) or (not email):
        return render_template("pre_enroll.html", source=source, subsource=subsource)
    else:
        return auth.send_enroll_token(source, subsource, email)


@app.route(f"{URL_PREFIX}/confirm_subscription/<link_data_raw>", methods=["GET"])
def enroll_with_token(link_data_raw):
    try:
        link_data: SignUpLinkData = from_hashed_base64(link_data_raw, HMAC_KEY, SignUpLinkData)
    except ValueError:
        return redirect(
            url_for(
                "pre_enroll_get",
                error="The enrollment link you used was invalid. Please request a new enrollment link below.",
            )
        )
    token = get_token(link_data.token_id)
    if (not link_data) or (not token):
        return redirect(
            url_for(
                "pre_enroll_get",
                source=link_data.source,
                subsource=link_data.subsource,
                error="The enrollment link you used was expired. Please request a new enrollment link below.",
            )
        )
    else:
        return render_template("enroll_with_token.html", link_data_raw=link_data_raw)


@app.route(f"{URL_PREFIX}/confirm_subscription/<link_data_raw>", methods=["POST"])
def enroll_with_token_post(link_data_raw):
    try:
        link_data: SignUpLinkData = from_hashed_base64(link_data_raw, HMAC_KEY, SignUpLinkData)
    except ValueError:
        return redirect(
            url_for(
                "pre_enroll_get",
                error="The enrollment link you used was invalid. Please request a new enrollment link below.",
            )
        )
    token = get_token(link_data.token_id)
    if (not link_data) or (not token):
        return redirect(
            url_for(
                "pre_enroll_get",
                source=link_data.source,
                subsource=link_data.subsource,
                error="The enrollment link you used was expired. Please request a new enrollment link below.",
            )
        )
    else:
        user_code = request.form.get("code")
        if token.code == user_code:
            return auth.enroll(link_data.email, link_data.source, link_data.subsource)
        else:
            # this would be a good place to delay if we wanted to prevent brute-force
            return render_template("enroll_with_token.html", link_data_raw=link_data_raw, code_error="Incorrect code!")


@app.route(f"{URL_PREFIX}/logout")
def logout():
    source = auth.get_source()
    subsource = auth.get_subsource()
    error_description = request.args.get("error_description")
    auth.logout(error_description)
    return redirect(url_for("pre_enroll_get", source=source, subsource=subsource))


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
        else:
            return render_template("pre_unsubscribe.html", error="Please choose an option below")
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

    return render_template("consent1.html", error=error, missing=missing)


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
    success = request.args.get("success")
    error = request.args.get("error_description")
    with DB_ENGINE.connect() as conn:
        account_repo = DbAccountRepository(conn)

        is_subscribed = False
        if auth.is_logged_in():
            subscription = account_repo.fetch_subscription_for_account(auth.get_account_id())
            is_subscribed = subscription is not None

        return render_template(
            "home.html",
            error=error,
            success=success,
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
            if request.is_json:
                data = request.get_json()
            else:
                data = request.form
            article_feedback_type = data.get("articlefeedbackType")
            newsletter_id = data.get("newsletter_id")
            impression_id = data.get("impression_id")

            # newsletter_id, impression_id, article_feedback_type = combined_value.split("||")

            if article_feedback_type == "positive":
                is_article_positive = True
            else:
                is_article_positive = False

            newsletter_repo.store_impression_feedback(impression_id, is_article_positive)
            impressions = newsletter_repo.fetch_impressions_by_newsletter_ids([newsletter_id])
            conn.commit()

            if request.is_json:
                return jsonify({"status": "ok", "feedback": is_article_positive})

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
        impressions=impressions,
        images=images,
    )


@app.route(f"{URL_PREFIX}/topics", methods=["GET", "POST"])
@auth.requires_login
def topics():
    onboarding = auth.get_account_status() == "pending_initial_preferences"

    # NOTE -- code in topics.html implicitly assumes this is sorted smallest to largest
    #         and that the numeric values are consecutive integers.
    interest_lvls = [
        ("Not at all interested", 1),
        ("Not particularly interested", 2),
        ("Somewhat interested", 3),
        ("Interested", 4),
        ("Very interested", 5),
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
                return redirect(url_for("demographic_form"))

        user_topic_preferences = get_topic_preferences(auth.get_account_id())

    else:  # topic get method
        user_topic_preferences = get_topic_preferences(auth.get_account_id())

    return render_template(
        "topics.html",
        updated=updated,
        onboarding=onboarding,
        topics=GENERAL_TOPICS,
        topic_hints=TOPIC_HINTS,
        intlvls=interest_lvls,
        user_topic_preferences=user_topic_preferences,
    )


@app.route(f"{URL_PREFIX}/entities", methods=["GET", "POST"])
@auth.requires_login
def entities():
    # NOTE -- code in entities.html implicitly assumes this is sorted smallest to largest
    #         and that the numeric values are consecutive integers.
    interest_lvls = [
        ("Not at all interested", 1),
        ("Not particularly interested", 2),
        ("Somewhat interested", 3),
        ("Interested", 4),
        ("Very interested", 5),
    ]

    def get_entity_preferences(account_id):
        with DB_ENGINE.connect() as conn:
            repo = DbAccountInterestRepository(conn)
            preferences = repo.fetch_entity_preferences(account_id)
        preferences_list = [
            {
                "entity_name": pref["entity_name"],
                "preference": pref["preference"],
                "entity_type": pref["entity_type"]
            }
            for pref in preferences
        ]
        preferences_dict = {pref["entity_name"]: pref["preference"] for pref in preferences}
        return preferences_list, preferences_dict

    def get_pref(entity_name):
        pref_score = request.form.get(entity_name.replace(" ", "_") + "_pref", None)
        if pref_score:
            return int(pref_score)
        else:
            return None

    updated = False
    searched_entities = []
    search_query = ""

    if request.method == "POST":
        with DB_ENGINE.connect() as conn:
            repo = DbAccountInterestRepository(conn)
            account_id = auth.get_account_id()

            # Check if it's a search
            search_query = request.form.get("search_query", "").strip()
            if search_query:
                searched_entities = repo.fetch_entities_by_partial_name(search_query, limit=20)
            else:
                # Handle ratings submission or removal
                save_entity = request.form.get("save")
                remove_entity = request.form.get("remove")
                
                if save_entity:
                    # Save a single entity preference
                    entity_name = save_entity
                    pref_key = entity_name.replace(" ", "_") + "_pref"
                    score = request.form.get(pref_key)
                    if score:
                        entity_id = repo.fetch_entity_by_name(entity_name)
                        if entity_id:
                            interest = AccountInterest(
                                account_id=account_id,
                                entity_id=entity_id,
                                entity_name=entity_name,
                                preference=int(score),
                                frequency=None,
                            )
                            repo.store_topic_preferences(account_id, [interest])
                            conn.commit()
                            updated = True
                
                elif remove_entity:
                    # Remove a single entity preference
                    entity_name = remove_entity
                    entity_id = repo.fetch_entity_by_name(entity_name)
                    if entity_id:
                        repo.remove_entity_preference(account_id, entity_id)
                        conn.commit()
                        updated = True

    user_entity_preferences_list, user_entity_preferences_dict = get_entity_preferences(auth.get_account_id())

    return render_template(
        "entities.html",
        updated=updated,
        searched_entities=searched_entities,
        search_query=search_query,
        intlvls=interest_lvls,
        user_entity_preferences=user_entity_preferences_list,
        user_entity_preferences_dict=user_entity_preferences_dict,
    )


@app.route(f"{URL_PREFIX}/demographic_survey", methods=["GET"])
@auth.requires_login
def demographic_form():
    onboarding = auth.get_account_status() == "pending_demographic_survey"

    updated = request.args.get("updated", False)

    user_demographic_information = fetch_demographic_information(auth.get_account_id())

    return render_template(
        "demographics_survey_form.html",
        updated=updated,
        onboarding=onboarding,
        genderopts=GENDER_OPTIONS,
        edlevelopts=EDUCATION_OPTIONS,
        raceopts=RACE_OPTIONS,
        clientopts=EMAIL_CLIENT_OPTIONS,
        user_demographic_information=user_demographic_information,
    )


@app.route(f"{URL_PREFIX}/update_demographics", methods=["POST"])
@auth.requires_login_ignore_status  # part of new_account workflow.
def update_demographics():
    onboarding = auth.get_account_status() == "pending_demographic_survey"

    with DB_ENGINE.connect() as conn:
        repo = DbDemographicsRepository(conn)
        account_repo = DbAccountRepository(conn)
        account_id = auth.get_account_id()

        def zip_validation(zip_code):
            if zip_code:
                if len(zip_code) == 5 and zip_code.isdigit():
                    return zip_code
            return "00000"

        def birthyear_validate(raw_birthyear):
            if raw_birthyear in {"", "0000", "0"}:
                return None
            return int(raw_birthyear)

        gender = validate(request.form.get("gender"), GENDER_OPTIONS)
        birthyear = birthyear_validate(request.form.get("birthyear"))
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

        # If `race_notlisted` has a value, add it to `race`
        if race_notlisted:
            race.append(race_notlisted)

        if email_client_other:
            email_client.append(email_client_other)

        required_ok = all(
            [
                gender,
                education,
                zip5,
                race,
                email_client,
            ]
        )

        if required_ok:  # None is falsy
            zip5 = zip5
            demo = Demographics(
                account_id=account_id,
                gender=gender,
                birth_year=birthyear,
                zip3=str(zip5)[:3],
                education=education,
                race=";".join(race) if isinstance(race, list) else race,
                email_client=";".join(email_client) if isinstance(email_client, list) else email_client,
            )

            repo.store_demographics(demo)
            account_repo.store_zip5(account_id, zip5)
            conn.commit()
        if onboarding:
            finish_demographic_survey(account_id)
            enqueue_newsletter_request(
                account_id=account_id,
                profile_id=account_id,
                group_id=None,
                recommender_url=DEFAULT_RECS_ENDPOINT_URL,
            )
            return redirect(url_for("compensation_preference_form"))
        else:
            return redirect(url_for("demographic_form", updated=True))


@app.route(f"{URL_PREFIX}/compensation_preference", methods=["GET"])
@auth.requires_login
def compensation_preference_form():
    onboarding = auth.get_account_status() == "pending_compensation_preference"

    updated = request.args.get("updated", False)

    def convert_to_category(compensation: str) -> dict[str, str]:
        selected_comp = {"method": "", "option": ""}

        if compensation is None:
            return selected_comp
        else:
            selected_comp["option"] = compensation

        if compensation in COMPENSATION_CARD_OPTIONS:
            selected_comp["method"] = "giftcard"
        elif compensation in COMPENSATION_CHARITY_OPTIONS:
            selected_comp["method"] = "donatecharity"
        else:
            selected_comp["method"] = "Decline payment"

        return selected_comp

    user_compensation = fetch_compensation_preferences(auth.get_account_id())
    user_compensation = convert_to_category(user_compensation)

    return render_template(
        "compensation_form.html",
        updated=updated,
        onboarding=onboarding,
        giftcardopts=COMPENSATION_CARD_OPTIONS,
        donationopts=COMPENSATION_CHARITY_OPTIONS,
        auth=auth,
        user_compensation=user_compensation,
    )


@app.route(f"{URL_PREFIX}/update_compensation_preference", methods=["POST"])
@auth.requires_login_ignore_status  # part of new_account workflow.
def update_compensation_preference():
    onboarding = auth.get_account_status() == "pending_compensation_preference"

    with DB_ENGINE.connect() as conn:
        account_repo = DbAccountRepository(conn)
        account_id = auth.get_account_id()

        compensation_choice = ""
        compensation_method = request.form.get("compensation_method")
        if compensation_method == "giftcard":
            compensation_choice = validate(request.form.get("selected_giftcard"), COMPENSATION_OPTIONS)
        elif compensation_method == "donatecharity":
            compensation_choice = validate(request.form.get("selected_charity"), COMPENSATION_OPTIONS)
        else:
            compensation_choice = validate(compensation_method, COMPENSATION_OPTIONS)

        account_repo.store_compensation(account_id, compensation_choice)
        conn.commit()

        if onboarding:
            finish_onboarding(account_id)
            enqueue_newsletter_request(
                account_id=account_id,
                profile_id=account_id,
                group_id=None,
                recommender_url=DEFAULT_RECS_ENDPOINT_URL,
            )
            completion_msg = "You have completed onboarding and are subscribed to POPROX! \
                You can now logout and expect your first newsletter to arrive shortly."
            return redirect(url_for("home", success=completion_msg))
        else:
            return redirect(url_for("compensation_preference_form", updated=True))


@app.route(f"{URL_PREFIX}/redirect/<path>", methods=["GET"])
def track_email_click(path):
    try:
        headers = {k: v for k, v in request.headers.items()}  # convert to conventional dict
        params = from_hashed_base64(path, HMAC_KEY, TrackingLinkData)
        logger.info(f"Processing message: {params.model_dump_json()}")
        with DB_ENGINE.connect() as conn:
            click_repo = DbClicksRepository(conn)
            click_repo.store_click(params.newsletter_id, params.account_id, params.article_id, headers)
            return redirect(params.url)
    except ValueError as e:
        # Don't retry if it doesn't have path parameters
        logger.error(f"Error processing message: {e}")
        return "Bad Request. Does not have required parameters", 400


if __name__ == "__main__":
    app.run(debug=True)
