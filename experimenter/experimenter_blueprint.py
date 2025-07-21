from datetime import date
from os import environ as env
from uuid import uuid4

import requests
import stamina
from flask import Blueprint, redirect, render_template, request, url_for
from poprox_storage.aws import DB_ENGINE
from poprox_storage.concepts.experiment import Recommender
from poprox_storage.repositories.accounts import DbAccountRepository
from poprox_storage.repositories.experience import DbExperiencesRepository
from poprox_storage.repositories.teams import DbTeamRepository

from poprox_concepts.domain.experience import Experience
from util.auth import auth

exp = Blueprint("experimenter", __name__, template_folder="templates", url_prefix="/dash")
EXPERENCE_TEST_URL = env.get("EXPERENCE_TEST_URL")

## EXPERIMENTER ROUTING


@exp.route("/")
@auth.requires_experimenter
def expt_home():
    return render_template(
        "experimenter_home.html", experiments=auth.get_account_experiments(), teams=auth.get_account_teams()
    )


## EXPERIMENT SPECIFIC TASKS and endpoints


@exp.route("/expt/<experiment_id>")
@auth.requires_experiment_team
def expt_dashboard(experiment_id):
    return render_template("experiment_dashboard.html", experiment=auth.get_account_experiments()[experiment_id])


## TEAM SPECIFIC TASKS and endpoints


@exp.get("/team/<team_id>")
@exp.get("/team/<team_id>/members")
@auth.requires_team_member
def team_dash_members(team_id):
    with DB_ENGINE.connect() as conn:
        team_repo = DbTeamRepository(conn)
        account_repo = DbAccountRepository(conn)
        team = team_repo.fetch_team_by_id(team_id)
        members = account_repo.fetch_accounts(team.members)
        return render_template("team_dash_members.html", team=team, members=members)


## TEAM EXPERIENCE SPECIFIC TASKS and endpoints


@exp.get("/team/<team_id>/experiences")
@auth.requires_team_member
def team_dash_experiences(team_id):
    with DB_ENGINE.connect() as conn:
        team_repo = DbTeamRepository(conn)
        experience_repo = DbExperiencesRepository(conn)
        experiences = experience_repo.fetch_experiences_by_team(team_id)
        team = team_repo.fetch_team_by_id(team_id)
        recommenders = {
            experience.recommender_id: experience_repo.fetch_recommender_url_by_id(experience.recommender_id)
            for experience in experiences
        }
        print(recommenders)
        return render_template(
            "team_dash_experiences.html", team=team, experiences=experiences, recommenders=recommenders
        )


@exp.get("/team/<team_id>/experiences/new")
@exp.get("/team/<team_id>/experiences/edit/<experience_id>")
@auth.requires_team_member
def team_edit_experience_form(team_id, experience_id=None, error=None):
    with DB_ENGINE.connect() as conn:
        team_repo = DbTeamRepository(conn)
        experience_repo = DbExperiencesRepository(conn)

        team = team_repo.fetch_team_by_id(team_id)
        experience = None
        recommender_url = None
        if experience_id:
            experience = experience_repo.fetch_experience_by_id(experience_id)
            recommender_url = experience_repo.fetch_recommender_url_by_id(experience.recommender_id)

        today = date.today()
        return render_template(
            "team_dash_new_experience.html",
            team=team,
            experience=experience,
            recommender_url=recommender_url,
            today=today,
            error=error,
        )


@exp.post("/team/<team_id>/experiences/new")
@exp.post("/team/<team_id>/experiences/edit/<experience_id>")
@auth.requires_team_member
def team_edit_experience_post(team_id, experience_id=None):
    try:
        name = request.form.get("name", "").strip()
        recommender_url = request.form.get("recommender_url", "").strip()
        start_date = request.form.get("start_date", "").strip()
        end_date = request.form.get("end_date", "").strip()
        template = request.form.get("template", "").strip()

        # validate required fields are not-empty
        if not (name and recommender_url and start_date):
            return team_edit_experience_form(team_id, experience_id, error="Missing required fields")

        start_date = date.fromisoformat(start_date)
        if end_date:
            end_date = date.fromisoformat(end_date)
        else:
            end_date = None
        if template == "":
            template = None

        recommender_id = None

        with DB_ENGINE.connect() as conn:
            team_repo = DbTeamRepository(conn)
            experience_repo = DbExperiencesRepository(conn)

            if experience_id:
                experience = experience_repo.fetch_experience_by_id(experience_id)
                old_recommender_url = experience_repo.fetch_recommender_url_by_id(experience.recommender_id)
                if old_recommender_url == recommender_url:
                    recommender_id = experience.recommender_id

            if recommender_id is None:
                recommender = Recommender(name=name + " recommender", url=recommender_url)
                recommender_id = team_repo.store_team_recommender(team_id, recommender)

            experience = Experience(
                experience_id=experience_id if experience_id else uuid4(),
                recommender_id=recommender_id,
                team_id=team_id,
                name=name,
                start_date=start_date,
                end_date=end_date,
                template=template,
            )
            experience_repo.store_experience(experience)
            conn.commit()
            return redirect(url_for("experimenter.team_dash_experiences", team_id=team_id))

    except Exception as e:
        # XXX: This swallows probably too many errors,
        # but given that errors might be caused by user-input here
        # I wanted to opt for feedback-over-logging.
        return team_edit_experience_form(team_id, experience_id, error=f"Unexpected Error {e}")


@exp.post("/team/<team_id>/experiences/test/<experience_id>")
@auth.requires_team_member
def team_experience_test_now(team_id, experience_id):
    if not EXPERENCE_TEST_URL:
        return redirect(
            url_for(
                "experimenter.team_dash_experiences",
                team_id=team_id,
                error="Experience testing not allowed without EXPERENCE_TEST_URL set in environment. You are probably "
                "in a testing environment where making this work is not advised in the first place.",
            )
        )

    try:
        for attempt in stamina.retry_context(
            on=(requests.HTTPError, requests.RequestException),
            attempts=3,
            wait_initial=30,
        ):
            with attempt:
                response = requests.post(
                    EXPERENCE_TEST_URL,
                    json={"team_id": team_id, "experience_id": experience_id},
                    timeout=30,
                )
                response.raise_for_status()

        return redirect(
            url_for(
                "experimenter.team_dash_experiences",
                team_id=team_id,
                error="TEST HAS BEEN TRIGGERED. give it a few minutes before asking us to check for errors.",
            )
        )

    except Exception as e:
        # XXX: This swallows probably too many errors,
        # but given that errors might be caused by user-input here
        # I wanted to opt for feedback-over-logging.
        return redirect(url_for("experimenter.team_dash_experiences", team_id=team_id, error=f"Unexpected Error {e}"))


## TEAM MEMBERS SPECIFIC TASKS and endpoints


@exp.post("/team/<team_id>/members")
@auth.requires_team_member
def add_to_team(team_id):
    email = request.form.get("email", "")
    with DB_ENGINE.connect() as conn:
        team_repo = DbTeamRepository(conn)
        account_repo = DbAccountRepository(conn)
        account = account_repo.fetch_account_by_email(email)
        if account is None:
            return redirect(
                url_for(
                    "experimenter.team_dash_members", team_id=team_id, error=f"No account for email: '{email}' found "
                )
            )
        team_repo.insert_team_membership(team_id, account.account_id)
        conn.commit()
        return redirect(url_for("experimenter.team_dash_members", team_id=team_id))
