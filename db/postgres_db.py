import logging
import os

from poprox_storage.repositories.accounts import DbAccountRepository
from sqlalchemy import create_engine

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

db_user = os.environ.get("POPROX_DB_USER", "postgres")
db_password = os.environ.get("POPROX_DB_PASSWORD", "postgres")
db_host = os.environ.get("POPROX_DB_HOST", "127.0.0.1")
db_port = os.environ.get("POPROX_DB_PORT", 5432)
db_name = os.environ.get("POPROX_DB_NAME", "poprox")

DB_URL = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
DB_ENGINE = create_engine(DB_URL, echo=False)


def get_or_make_account(email, source):
    with DB_ENGINE.connect() as conn:
        account_repo = DbAccountRepository(conn)
        result = account_repo.fetch_account_by_email(email)
        if result is None:
            result = account_repo.store_new_account(email, source)
            conn.commit()
        return {
            "account_id": result.account_id,
            "email": result.email,
            "status": result.status,
        }


def get_account(account_id):
    with DB_ENGINE.connect() as conn:
        account_repo = DbAccountRepository(conn)
        result = account_repo.fetch_accounts([account_id])
        if len(result) != 1:
            return None
        else:
            result = result[0]
            return {
                "account_id": result.account_id,
                "email": result.email,
                "status": result.status,
            }


def finish_consent(account_id, consent_version):
    with DB_ENGINE.connect() as conn:
        account_repo = DbAccountRepository(conn)
        account_repo.store_consent(account_id, consent_version)
        account_repo.update_status(account_id, "pending_initial_preferences")
        conn.commit()


def finish_onboarding(account_id):
    with DB_ENGINE.connect() as conn:
        account_repo = DbAccountRepository(conn)
        account_repo.update_status(account_id, "onboarding_done")
        account_repo.store_subscription_for_account(account_id)
        conn.commit()
