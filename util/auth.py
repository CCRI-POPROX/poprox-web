import json
import logging
from datetime import datetime, timezone
from functools import wraps
from os import environ as env

import jinja2
from flask import redirect, request, session, url_for
from poprox_storage.aws import sqs
from werkzeug.wrappers import Response

from poprox_concepts.api.tracking import SignUpLinkData, to_hashed_base64
from util.postgres_db import create_token, get_account, get_or_make_account

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

HMAC_KEY = env.get("POPROX_HMAC_KEY", "defaultpoproxhmackey")


STATUS_REDIRECTS = {
    "new_account": "consent1",
    "pending_initial_preferences": "topics",
}


class Auth:
    def __init__(self) -> None:
        pass

    def enroll(self, email, source, subsource) -> Response:
        session["account"] = get_or_make_account(email, source, subsource)
        return redirect(url_for(STATUS_REDIRECTS.get(self.get_account_status(), "home")))

    def login_via_account_id(self, account_id):
        session["account"] = get_account(account_id)

    def is_logged_in(self):
        return "account" in session

    def refresh_account_info(self):
        session["account"] = get_account(self.get_account_id())

    def get_email(self):
        if self.is_logged_in():
            return session["account"]["email"]
        else:
            return None

    def get_account_id(self):
        if self.is_logged_in():
            return session["account"]["account_id"]
        else:
            return None

    def get_account_status(self):
        if self.is_logged_in():
            self.refresh_account_info()  # status can change over time sometimes...
            return session["account"]["status"]
        else:
            return None

    def is_new(self):
        if self.is_logged_in():
            return session["account"]["is_new"]
        else:
            return None

    def get_account_teams(self):
        if self.is_logged_in():
            return session["account"]["teams"]
        else:
            return None

    def get_account_experiments(self):
        if self.is_logged_in():
            return session["account"]["experiments"]
        else:
            return None

    def requires_login(self, f):
        @wraps(f)
        def decorated(*args, **kwargs):
            endpoint = request.endpoint
            expected_endpoint = STATUS_REDIRECTS.get(self.get_account_status())
            if self.is_logged_in() and expected_endpoint is not None and endpoint != expected_endpoint:
                return redirect(url_for(STATUS_REDIRECTS[self.get_account_status()]))
            elif self.is_logged_in():
                return f(*args, **kwargs)
            else:
                return redirect(url_for("pre_enroll_get"))

        return decorated

    def requires_experiment_team(self, f):
        @wraps(f)
        def decorated(experiment_id, *args, **kwargs):
            endpoint = request.endpoint
            expected_endpoint = STATUS_REDIRECTS.get(self.get_account_status())
            if self.is_logged_in() and expected_endpoint is not None and endpoint != expected_endpoint:
                return redirect(url_for(STATUS_REDIRECTS[self.get_account_status()]))
            elif self.is_logged_in() and experiment_id not in self.get_account_experiments():
                return redirect(url_for("experimenter.expt_home"))
            elif self.is_logged_in() and experiment_id in self.get_account_experiments():
                return f(experiment_id, *args, **kwargs)
            else:
                return redirect(url_for("pre_enroll_get"))

        return decorated

    def requires_team_member(self, f):
        @wraps(f)
        def decorated(team_id, *args, **kwargs):
            endpoint = request.endpoint
            expected_endpoint = STATUS_REDIRECTS.get(self.get_account_status())
            if self.is_logged_in() and expected_endpoint is not None and endpoint != expected_endpoint:
                return redirect(url_for(STATUS_REDIRECTS[self.get_account_status()]))
            elif self.is_logged_in() and team_id not in self.get_account_teams():
                return redirect(url_for("experimenter.expt_home"))
            elif self.is_logged_in() and team_id in self.get_account_teams():
                return f(team_id, *args, **kwargs)
            else:
                return redirect(url_for("pre_enroll_get"))

        return decorated

    def requires_experimenter(self, f):
        @wraps(f)
        def decorated(*args, **kwargs):
            endpoint = request.endpoint
            expected_endpoint = STATUS_REDIRECTS.get(self.get_account_status())
            if self.is_logged_in() and expected_endpoint is not None and endpoint != expected_endpoint:
                return redirect(url_for(STATUS_REDIRECTS[self.get_account_status()]))
            elif self.is_logged_in() and len(self.get_account_teams()) == 0:
                return redirect(url_for("home"))
            elif self.is_logged_in() and len(self.get_account_teams()) > 0:
                return f(*args, **kwargs)
            else:
                return redirect(url_for("pre_enroll_get"))

        return decorated

    def requires_login_ignore_status(self, f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if self.is_logged_in():
                return f(*args, **kwargs)
            else:
                return redirect(url_for("home"))

        return decorated

    @staticmethod
    def logout(error_description=None) -> str:
        session.clear()

    def send_enroll_token(self, source, subsource, email):
        queue_url = env.get("SEND_EMAIL_QUEUE_URL")

        token = create_token()

        link_data = SignUpLinkData(
            email=email,
            source=source,
            subsource=subsource,
            created_at=datetime.now(timezone.utc).astimezone(),
            token_id=token.token_id,
        )
        link_data_signed = to_hashed_base64(link_data, HMAC_KEY)

        jinja_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader("email_templates"),
            autoescape=jinja2.select_autoescape(),
        )

        template = jinja_env.get_template("enroll_token_email.html")
        enroll_link = url_for("enroll_with_token", link_data_raw=link_data_signed, _external=True)
        html = template.render(enroll_link=enroll_link, token=token)
        message = json.dumps(
            {
                "email_to": email,
                "email_subject": "Welcome to POPROX",
                "email_body": html,
            }
        )
        if queue_url:
            sqs.send_message(queue_url=queue_url, message_body=message)
        else:
            logger.error("No email queue url is sent. This is OK in development.")
            logger.error("to: " + email)
            logger.error("subject: " + "POPROX - Record of Consent")
            import html_previewer

            html_previewer.preview(html)
        return redirect(enroll_link)

    def send_post_consent(self):
        queue_url = env.get("SEND_EMAIL_QUEUE_URL")
        email = self.get_email()

        jinja_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader("email_templates"),
            autoescape=jinja2.select_autoescape(),
        )

        template = jinja_env.get_template("enroll_post_consent.html")
        html = template.render(
            consent_form_link=url_for("static", filename="Subscriber_Agreement_v2.pdf", _external=True)
        )
        message = json.dumps(
            {
                "email_to": email,
                "email_subject": "POPROX - Record of Consent",
                "email_body": html,
            }
        )
        if queue_url:
            sqs.send_message(queue_url=queue_url, message_body=message)
        else:
            logger.error("No email queue url is sent. This is OK in development.")
            logger.error("to: " + email)
            logger.error("subject: " + "POPROX - Record of Consent")
            import html_previewer

            html_previewer.preview(html)


auth = Auth()
