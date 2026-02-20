import logging
import os
from datetime import datetime, timedelta, timezone

from poprox_storage.repositories.accounts import DbAccountRepository
from poprox_storage.repositories.clicks import DbClicksRepository
from poprox_storage.repositories.demographics import DbDemographicsRepository
from poprox_storage.repositories.experiments import DbExperimentRepository
from poprox_storage.repositories.qualtrics_survey import DbQualtricsSurveyRepository
from poprox_storage.repositories.subscriptions import DbSubscriptionRepository
from poprox_storage.repositories.teams import DbTeamRepository
from poprox_storage.repositories.tokens import DbTokenRepository
from sqlalchemy import create_engine

from poprox_concepts.api.click_filtering import filter_click_histories
from poprox_concepts.api.tracking import Token
from poprox_concepts.domain.demographics import (
    EMAIL_CLIENT_OPTIONS,
    RACE_OPTIONS,
    Demographics,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

db_user = os.environ.get("POPROX_DB_USER", "postgres")
db_password = os.environ.get("POPROX_DB_PASSWORD", "postgres")
db_host = os.environ.get("POPROX_DB_HOST", "127.0.0.1")
db_port = os.environ.get("POPROX_DB_PORT", 5432)
db_name = os.environ.get("POPROX_DB_NAME", "poprox")

DB_URL = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
DB_ENGINE = create_engine(DB_URL, echo=False)
TOKEN_EXPIRATION = timedelta(hours=1)  # tokens for email are valid for 1 hour.


def get_or_make_account(email, source, subsource):
    with DB_ENGINE.connect() as conn:
        account_repo = DbAccountRepository(conn)
        result = account_repo.fetch_account_by_email(email)
        if result is None:
            result = account_repo.store_new_account(email, source, subsource)
            conn.commit()
        return {
            "account_id": result.account_id,
            "email": result.email,
            "status": result.status,
            "source": result.source,
            "subsource": result.subsource,
        }


def get_account(account_id):
    with DB_ENGINE.connect() as conn:
        account_repo = DbAccountRepository(conn)
        team_repo = DbTeamRepository(conn)
        expt_repo = DbExperimentRepository(conn)
        result = account_repo.fetch_accounts([account_id])
        if len(result) != 1:
            return None
        else:
            result = result[0]
            result = {
                "account_id": result.account_id,
                "email": result.email,
                "status": result.status,
                "source": result.source,
                "subsource": result.subsource,
            }
            result["teams"] = team_repo.fetch_teams_for_account(result["account_id"])
            result["experiments"] = expt_repo.fetch_experiments_by_team(list(result["teams"]))
            result["teams"] = {str(k): v.model_dump() for k, v in result["teams"].items()}
            result["experiments"] = {str(k): v.model_dump() for k, v in result["experiments"].items()}
            return result


def get_account_by_email(email):
    with DB_ENGINE.connect() as conn:
        account_repo = DbAccountRepository(conn)
        account = account_repo.fetch_account_by_email(email)
        if account:
            return {
                "account_id": account.account_id,
                "email": account.email,
                "status": account.status,
            }
        return None


def finish_consent(account_id, consent_version):
    with DB_ENGINE.connect() as conn:
        account_repo = DbAccountRepository(conn)
        account_repo.store_consent(account_id, consent_version)
        account_repo.update_status(account_id, "pending_initial_preferences")
        conn.commit()


def finish_topic_selection(account_id):
    with DB_ENGINE.connect() as conn:
        account_repo = DbAccountRepository(conn)
        account_repo.update_status(account_id, "pending_demographic_survey")
        conn.commit()


def finish_demographic_survey(account_id):
    with DB_ENGINE.connect() as conn:
        account_repo = DbAccountRepository(conn)
        account_repo.update_status(account_id, "pending_compensation_preference")
        conn.commit()


def finish_onboarding(account_id):
    with DB_ENGINE.connect() as conn:
        account_repo = DbAccountRepository(conn)
        account_repo.update_status(account_id, "onboarding_done")

        subscription_repo = DbSubscriptionRepository(conn)
        subscription_repo.store_subscription_for_account(account_id)
        conn.commit()


def create_token() -> Token:
    with DB_ENGINE.connect() as conn:
        token_repo = DbTokenRepository(conn)
        token = token_repo.create_token()
        conn.commit()
        return token


def get_token(token_id) -> Token | None:
    now = datetime.now(timezone.utc).astimezone()
    with DB_ENGINE.connect() as conn:
        token_repo = DbTokenRepository(conn)
        token = token_repo.fetch_token_by_id(token_id)
        if token is None:
            return None
        elif (now - token.created_at) > TOKEN_EXPIRATION:
            # token is too old for this purpose
            return None
        else:
            return token


def fetch_demographic_information(account_id):
    def convert_to_record(row: Demographics, zip5: str) -> dict:
        race_list = row.race.split(";")  # Split the race field into individual races
        predefined_races = [r for r in race_list if r in RACE_OPTIONS]
        custom_races = next((r for r in race_list if r not in RACE_OPTIONS), None)

        email_client_list = row.email_client.split(";")
        predefined_email_clients = [e for e in email_client_list if e in EMAIL_CLIENT_OPTIONS]
        custom_email_clients = next((e for e in email_client_list if e not in EMAIL_CLIENT_OPTIONS), None)
        return {
            "gender": row.gender,
            "birth_year": row.birth_year,
            "zip5": zip5,
            "education": row.education,
            "raw_race": row.race,
            "race": ";".join(predefined_races),  # Join predefined races back into a single string
            "race_notlisted": custom_races,
            "raw_email_client": row.email_client,
            "email_client": ";".join(predefined_email_clients),
            "email_client_other": custom_email_clients,
        }

    with DB_ENGINE.connect() as conn:
        repo = DbDemographicsRepository(conn)
        account_repo = DbAccountRepository(conn)
        demographics = repo.fetch_latest_demographics_by_account_id(account_id)
        zip5 = account_repo.fetch_zip5(account_id)

        if demographics and zip5:
            combined_dict = convert_to_record(demographics, zip5)
            return combined_dict
        else:
            return None


def fetch_compensation_preferences(account_id):
    with DB_ENGINE.connect() as conn:
        account_repo = DbAccountRepository(conn)
        compensation = account_repo.fetch_compensation(account_id)

    return compensation


def fetch_user_click_and_survey_activity(account_id, start_date, end_date):
    with DB_ENGINE.connect() as conn:
        account_repo = DbAccountRepository(conn)
        click_repo = DbClicksRepository(conn)
        survey_repo = DbQualtricsSurveyRepository(conn)
        account = account_repo.fetch_accounts([account_id])
        user_click_activity = click_repo.fetch_clicks_between(start_date, end_date, account)
        click_count = 0
        survey_count = 0

        if account_id in user_click_activity:
            filtered_clicks = filter_click_histories(user_click_activity)
            clicked_newsletters = set()
            for click in filtered_clicks[account_id]:
                clicked_newsletters.add(click.newsletter_id)
            click_count = len(clicked_newsletters)

        user_survey_activity = survey_repo.fetch_clean_responses_between(start_date, end_date, account)
        survey_count = len(user_survey_activity)
        return {
            "click_count": click_count,
            "survey_count": survey_count,
        }
