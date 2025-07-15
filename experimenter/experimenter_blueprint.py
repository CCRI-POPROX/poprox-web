from flask import Blueprint, redirect, render_template, request, url_for
from poprox_storage.aws import DB_ENGINE
from poprox_storage.repositories.accounts import DbAccountRepository
from poprox_storage.repositories.teams import DbTeamRepository

from util.auth import auth

exp = Blueprint("experimenter", __name__, template_folder="templates", url_prefix="/dash")


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
def team_dashboard(team_id):
    with DB_ENGINE.connect() as conn:
        team_repo = DbTeamRepository(conn)
        account_repo = DbAccountRepository(conn)
        team = team_repo.fetch_team_by_id(team_id)
        members = account_repo.fetch_accounts(team.members)
        return render_template("team_dashboard.html", team=team, members=members)


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
                url_for("experimenter.team_dashboard", team_id=team_id, error=f"No account for email: '{email}' found ")
            )
        team_repo.insert_team_membership(team_id, account.account_id)
        conn.commit()
        return redirect(url_for("experimenter.team_dashboard", team_id=team_id))
