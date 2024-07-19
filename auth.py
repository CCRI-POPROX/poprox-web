from functools import wraps
from os import environ as env
from typing import Optional
from urllib.parse import quote_plus, urlencode

from authlib.integrations.flask_client import OAuth
from flask import Flask, redirect, session, url_for
from werkzeug.local import LocalProxy
from werkzeug.wrappers import Response

from db.postgres_db import get_account, get_or_make_account

oauth = OAuth()

STATUS_REDIRECTS = {
    "new_account": "consent1",
    "waiting_email_verification": "await_email_verification",
}


class Auth:
    def __init__(self, app: Flask) -> None:
        oauth.init_app(app)
        self.__registered_app = None

    def __get_app(self) -> Optional[LocalProxy]:
        if self.__registered_app is None:
            self.__registered_app = oauth.register(
                "auth0",
                client_id=env.get("AUTH0_CLIENT_ID"),
                client_secret=env.get("AUTH0_CLIENT_SECRET"),
                client_kwargs={
                    "scope": "openid profile email update:users",
                },
                server_metadata_url=f'https://{env.get("AUTH0_DOMAIN")}/.well-known/openid-configuration',
            )
        return self.__registered_app

    def login(self):
        return self.__get_app().authorize_redirect(
            redirect_uri=url_for("callback", _external=True),
        )

    def register(self, source):
        return self.__get_app().authorize_redirect(
            redirect_uri=url_for("callback", _external=True, source=source),
            screen_hint="signup",
        )

    def callback(self, source) -> Response:
        auth0 = self.__get_app()
        auth_token = auth0.authorize_access_token()
        session["auth0_info"] = auth_token
        session["account"] = get_or_make_account(auth_token["userinfo"]["email"], source)
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
        self.refresh_account_info()  # status can change over time sometimes...
        if self.is_logged_in():
            return session["account"]["status"]
        else:
            return None

    def is_new(self):
        if self.is_logged_in():
            return session["account"]["is_new"]
        else:
            return None

    def requires_login(self, f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if self.is_logged_in() and self.get_account_status() in STATUS_REDIRECTS:
                return redirect(url_for(STATUS_REDIRECTS[self.get_account_status()]))
            elif self.is_logged_in():
                return f(*args, **kwargs)
            else:
                return redirect(url_for("home"))

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
        return (
            "https://"
            + env.get("AUTH0_DOMAIN")
            + "/v2/logout?"
            + urlencode(
                {
                    "returnTo": url_for("home", _external=True, error_description=error_description),
                    "client_id": env.get("AUTH0_CLIENT_ID"),
                },
                quote_via=quote_plus,
            )
        )

    def fetch_is_email_verified(self):
        return self.__get_app().userinfo(token=session["auth0_info"])["email_verified"]
