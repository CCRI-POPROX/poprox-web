from collections import defaultdict
from datetime import date
from uuid import UUID, uuid4

from flask import Blueprint, jsonify, redirect, render_template, request, url_for
from flask_httpauth import HTTPBasicAuth
from poprox_storage.aws import DB_ENGINE
from poprox_storage.concepts.experiment import Team
from poprox_storage.repositories import (
    DbAccountInterestRepository,
    DbAccountRepository,
    DbClicksRepository,
    DbExperimentRepository,
    DbNewsletterRepository,
    DbQualtricsSurveyRepository,
    DbSubscriptionRepository,
    DbTeamRepository,
)
from sqlalchemy.exc import IntegrityError, InternalError
from werkzeug.security import check_password_hash, generate_password_hash

from poprox_concepts.api.click_filtering import filter_click_histories
from poprox_concepts.domain.click import Click
from util.config import require_secret

admin = Blueprint("admin", __name__, template_folder="templates", url_prefix="/admin")
admin_auth = HTTPBasicAuth()

users = {
    "admin": generate_password_hash(require_secret("POPROX_WEB_ADMIN_PASS", "admin")),
}
PRE_STUDY_SURVEY_ID = UUID("6ba2e7f9-b63c-4abd-8823-d45eeb564a1d")
ENTITY_TYPES = {"person", "organization", "place"}


@admin_auth.verify_password
def verify_password(username, password):
    if username in users and check_password_hash(users.get(username), password):
        return username


@admin.get("/")
@admin_auth.login_required
def show():
    error = request.args.get("error")

    with DB_ENGINE.connect() as conn:
        experiment_repo = DbExperimentRepository(conn)
        today = date.today()

        active_experiments = experiment_repo.fetch_all_active_experiments(today)

    return render_template(
        "admin_home.html",
        error=error,
        active_experiments=active_experiments,
        today=today,
    )


@admin.get("/api/entity-study-eligibility")
@admin_auth.login_required
def get_entity_study_eligibility():
    with DB_ENGINE.connect() as conn:
        account_repo = DbAccountRepository(conn)
        subscriber_ids = DbSubscriptionRepository(conn).fetch_subscriber_account_ids()
        subscribers = account_repo.fetch_accounts(subscriber_ids)
        external_accounts = []
        for account in subscribers:
            if account.external:
                external_accounts.append(account)

        candidates = []
        if external_accounts:
            external_ids = []
            for account in external_accounts:
                external_ids.append(account.account_id)

            consented_ids = set()
            for log in account_repo.fetch_consent_logs_by_account_ids(external_ids):
                if log.ended_at is None:
                    consented_ids.add(log.account_id)

            for account in external_accounts:
                if account.account_id in consented_ids:
                    candidates.append(account)

        finished_accounts = []
        if candidates:
            survey_repo = DbQualtricsSurveyRepository(conn)
            instance_ids = []
            for instance in survey_repo.fetch_sent_survey_instances(candidates):
                if instance.survey_id == PRE_STUDY_SURVEY_ID:
                    instance_ids.append(instance.survey_instance_id)

            if instance_ids:
                finished_ids = set()
                for response in survey_repo.fetch_clean_responses_by_instance_ids(instance_ids):
                    if str(response.response_values.get("finished")).lower() in ("1", "true"):
                        finished_ids.add(response.account_id)

                for account in candidates:
                    if account.account_id in finished_ids:
                        finished_accounts.append(account)

        rated_enough = 0
        if finished_accounts:
            interest_repo = DbAccountInterestRepository(conn)
            for account in finished_accounts:
                rating_count = 0
                for interest in interest_repo.fetch_account_interests(account.account_id):
                    if interest.entity_type in ENTITY_TYPES:
                        rating_count += 1
                if rating_count >= 5:
                    rated_enough += 1

    return jsonify(
        {
            "subscribed_and_consented": len(candidates),
            "finished_pre_study_survey": len(finished_accounts),
            "rated_enough_entities": rated_enough,
        }
    )


### DATA API ###
@admin.get("/api/clicks/by_day")
@admin_auth.login_required
def get_clicks_by_day():
    # flag parameter, include as `...&include_all&...` or `...&include_all=True&...`
    include_all = request.args.get("include_all") is not None
    days_ago = int(request.args.get("days_ago", 31))

    # quite frankly, this doesn't look very efficient.
    with DB_ENGINE.connect() as conn:
        dbClicksRepository: DbClicksRepository = DbClicksRepository(conn)
        dbNewsletterRepository: DbNewsletterRepository = DbNewsletterRepository(conn)
        dbAccountRepository: DbAccountRepository = DbAccountRepository(conn)

        print("fetching valid clicks")
        # Fetch all valid clicks and newsletters
        valid_accounts = dbAccountRepository.fetch_accounts()
        if not include_all:
            valid_accounts = [account for account in valid_accounts if account.external]
        print(f"fetched {len(valid_accounts)} accounts")
        newsletters = dbNewsletterRepository.fetch_newsletters_since(
            days_ago=days_ago, accounts=valid_accounts, shallow=True
        )
        print(f"fetched {len(newsletters)} newsletters")
        clicks_by_account = dbClicksRepository.fetch_clicks_by_newsletter_ids(
            [newsletter.newsletter_id for newsletter in newsletters]
        )
        clicks_by_account = filter_click_histories(clicks_by_account)
        print("fetched clicks")
        # aggregate to counts-per-day.
        clicks_by_newsletter: dict[UUID, list[Click]] = defaultdict(list)
        for account, clicks in clicks_by_account.items():
            for click in clicks:
                clicks_by_newsletter[click.newsletter_id].append(click)
        clicks_by_day: dict[date, int] = defaultdict(int)
        for newsletter in newsletters:
            newsletter_date = newsletter.created_at.date()
            clicks_by_day[newsletter_date] += len(clicks_by_newsletter[newsletter.newsletter_id])
        return jsonify({k.isoformat(): v for k, v in clicks_by_day.items()})


### TEAM MANAGEMENT ###


@admin.get("/team")
@admin_auth.login_required
def team_manage():
    error = request.args.get("error")
    with DB_ENGINE.connect() as conn:
        team_repo = DbTeamRepository(conn)
        teams = team_repo.fetch_teams()
        return render_template("admin_team_management.html", error=error, teams=teams)


@admin.get("/team/<team_id>")
@admin_auth.login_required
def team_details(team_id):
    error = request.args.get("error")

    with DB_ENGINE.connect() as conn:
        team_repo = DbTeamRepository(conn)
        account_repo = DbAccountRepository(conn)
        team = team_repo.fetch_team_by_id(team_id)
        members = account_repo.fetch_accounts(team.members)
        return render_template("admin_edit_team.html", team=team, error=error, members=members)


@admin.post("/team/<team_id>")
@admin_auth.login_required
def edit_team_name(team_id):
    new_name = request.form.get("team_name")
    with DB_ENGINE.connect() as conn:
        team_repo = DbTeamRepository(conn)
        account_repo = DbAccountRepository(conn)

        team = team_repo.fetch_team_by_id(team_id)
        team.team_name = new_name
        team_repo.store_team(team)
        members = account_repo.fetch_accounts(team.members)

        conn.commit()
        return render_template("admin_edit_team.html", team=team, members=members)


@admin.post("/team/<team_id>/members")
@admin_auth.login_required
def add_to_team(team_id):
    email = request.form.get("email", "")
    with DB_ENGINE.connect() as conn:
        team_repo = DbTeamRepository(conn)
        account_repo = DbAccountRepository(conn)
        account = account_repo.fetch_account_by_email(email)
        if account is None:
            return redirect(
                url_for("admin.team_details", team_id=team_id, error=f"No account for email: '{email}' found ")
            )
        try:
            team_repo.insert_team_membership(team_id, account.account_id)
            conn.commit()
            return redirect(url_for("admin.team_details", team_id=team_id))
        except ValueError as e:
            return redirect(url_for("admin.team_details", team_id=team_id, error=str(e)))


@admin.post("/team")
@admin_auth.login_required
def new_team():
    team_name = request.form.get("team_name", "untitled team")
    with DB_ENGINE.connect() as conn:
        team_repo = DbTeamRepository(conn)
        team = Team(team_id=uuid4(), team_name=team_name, members=[])
        team_repo.store_team(team)
        conn.commit()
        return redirect(url_for("admin.team_details", team_id=team.team_id))


### ACCOUNT MANAGEMENT


@admin.get("/account")
@admin_auth.login_required
def account_search():
    accounts = []
    with DB_ENGINE.connect() as conn:
        account_repo = DbAccountRepository(conn)
        if request.args.get("account_id"):
            accounts = account_repo.fetch_accounts(request.args["account_id"])
        elif request.args.get("account_email_query"):
            accounts = account_repo.fetch_account_by_email_query(request.args["account_email_query"])

    return render_template("admin_account_management.html", accounts=accounts)


@admin.get("/account/<account_id>")
@admin_auth.login_required
def account_detail(account_id):
    with DB_ENGINE.connect() as conn:
        account_repo = DbAccountRepository(conn)
        account = account_repo.fetch_accounts([account_id])
        if len(account) == 0:
            redirect(url_for("admin.account_search", error="account not found"))
        else:
            account = account[0]

    return render_template("admin_account_detail.html", editable=["source", "subsource", "email"], account=account)


@admin.post("/account/<account_id>")
@admin_auth.login_required
def update_account_detail(account_id):
    with DB_ENGINE.connect() as conn:
        account_repo = DbAccountRepository(conn)
        account = account_repo.fetch_accounts([account_id])
        if len(account) == 0:
            redirect(url_for("admin.account_search", error="account not found"))
        else:
            account = account[0]

        if request.form.get("source"):
            account.source = request.form.get("source")
        if request.form.get("subsource"):
            account.subsource = request.form.get("subsource")
        if request.form.get("email"):
            account.email = request.form.get("email")

        try:
            account_repo.store_account(account, commit=False)
            conn.commit()
        except (IntegrityError, InternalError) as err:
            conn.rollback()
            return redirect(
                url_for("admin.account_detail", account_id=account_id, error="update not applied: " + str(err))
            )

    return render_template("admin_account_detail.html", editable=["source", "subsource", "email"], account=account)


@admin.post("/account/<account_id>/force_unsubscribe")
@admin_auth.login_required
def force_unsubscribe(account_id):
    if request.form.get("confirm"):
        try:
            with DB_ENGINE.connect() as conn:
                subscription_repo = DbSubscriptionRepository(conn)
                account_repo = DbAccountRepository(conn)

                subscription_repo.remove_subscription_for_account(account_id)
                account_repo.update_status(account_id, "admin unsubscribe")
                conn.commit()

                return redirect(url_for("admin.account_detail", account_id=account_id, error="unsubbed"))
        except (IntegrityError, InternalError) as err:
            conn.rollback()
            return redirect(
                url_for("admin.account_detail", account_id=account_id, error="update not applied: " + str(err))
            )
    else:
        return redirect(
            url_for("admin.account_detail", account_id=account_id, error="update not applied. you gotta confirm")
        )
