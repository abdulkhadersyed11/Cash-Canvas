"""Streamlit authentication page for CashCanvas."""

from __future__ import annotations

import bcrypt
import streamlit as st

from database.db_operations import create_user, get_user_by_username


def ensure_session_defaults() -> None:
    """Initialize the session keys used by the auth flow."""

    st.session_state.setdefault("logged_in", False)
    st.session_state.setdefault("user_id", None)
    st.session_state.setdefault("username", "")


def hash_password(password: str) -> str:
    """Return a bcrypt hash for the provided password."""

    password_bytes = password.encode("utf-8")
    hashed_bytes = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
    return hashed_bytes.decode("utf-8")


def verify_password(password: str, stored_hash: str) -> bool:
    """Check whether a password matches the stored bcrypt hash."""

    password_bytes = password.encode("utf-8")
    stored_hash_bytes = stored_hash.encode("utf-8")
    return bcrypt.checkpw(password_bytes, stored_hash_bytes)


def register_user(username: str, email: str, password: str) -> None:
    """Create a new user after validating the username and hashing the password."""

    username = username.strip()
    email = email.strip()

    if not username or not email or not password:
        st.error("Please fill in all registration fields.")
        return

    existing_user = get_user_by_username(username)
    if existing_user is not None:
        st.error("That username is already taken. Please choose another one.")
        return

    password_hash = hash_password(password)
    created_user_id = create_user(username, email, password_hash)

    if created_user_id is None:
        st.error("Registration failed. Please try a different email address.")
        return

    st.success("Registration successful. You can now log in.")


def login_user(username: str, password: str) -> bool:
    """Authenticate a user and populate the Streamlit session state on success."""

    username = username.strip()

    if not username or not password:
        st.error("Invalid username or password.")
        return False

    user = get_user_by_username(username)

    # Keep the failure message generic so the page does not reveal which field was wrong.
    if user is None or not verify_password(password, user["password_hash"]):
        st.error("Invalid username or password.")
        return False

    st.session_state["logged_in"] = True
    st.session_state["user_id"] = user["user_id"]
    st.session_state["username"] = user["username"]
    return True


def render_login_tab() -> None:
    """Render the login form."""

    with st.form("login_form"):
        username = st.text_input("Username", key="login_username")
        password = st.text_input("Password", type="password", key="login_password")
        submitted = st.form_submit_button("Log in")

        if submitted and login_user(username, password):
            st.session_state["pending_page"] = "📊 Dashboard"
            st.rerun()


def render_register_tab() -> None:
    """Render the registration form."""

    with st.form("register_form"):
        username = st.text_input("Username", key="register_username")
        email = st.text_input("Email", key="register_email")
        password = st.text_input("Password", type="password", key="register_password")
        submitted = st.form_submit_button("Create account")

        if submitted:
            register_user(username, email, password)


def main() -> None:
    """Render the CashCanvas authentication page."""

    st.title("CashCanvas")
    st.subheader("Sign in or create a new account")

    ensure_session_defaults()

    login_tab, register_tab = st.tabs(["Login", "Register"])

    with login_tab:
        render_login_tab()

    with register_tab:
        render_register_tab()


if __name__ == "__main__":
    main()
