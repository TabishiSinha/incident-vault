"""
Authentication gate for Incident Vault.

Two modes, picked automatically from secrets — no code changes needed to
switch between them:

  [auth]           Real sign-in via st.login() (OIDC). Works with Microsoft
                    Entra ID (your org account), Google, Okta, or any OIDC
                    provider. Ties each person's real identity to the app,
                    which lets the Approvals tab check that the logged-in
                    user's email actually matches the approver on a step
                    before letting them click Approve/Reject. Needs an
                    Azure AD (or other IdP) app registration — see README.

                    The main restriction to "only our org can sign in" is
                    enforced by the IdP itself (a single-tenant Azure AD
                    app registration rejects outside accounts before this
                    code ever runs). Two optional keys inside [auth] add a
                    backstop check in the app too, in case that's ever
                    misconfigured:

                      allowed_tenant_id = "..."          # Entra ID tenant GUID
                      allowed_email_domains = ["accenture.com"]

  app_password      A single shared password gate. No per-user identity —
                    just keeps random visitors out. No IT setup needed,
                    good for getting something running today.

                    Add email_domains (top-level, alongside app_password)
                    to also require a work email at login, restricted to
                    the domains you list:

                      app_password = "..."
                      email_domains = ["accenture.com"]

                    IMPORTANT: this is NOT verified identity — anyone who
                    knows the password can type any email that matches the
                    domain. It's a self-declared identity, useful for
                    letting the Approvals tab know who's likely acting and
                    for the domain check at the door, but it does not
                    cryptographically confirm the person is who they say.
                    Real verification is the [auth] OIDC option above,
                    once you have it — this is the practical option before
                    that's set up.

  neither set       App runs unauthenticated, with a visible warning banner.
                    Fine for local testing. Not for anything real.
"""

import streamlit as st


def _oidc_configured():
    return "auth" in st.secrets


def _password_configured():
    return "app_password" in st.secrets


def mode():
    if _oidc_configured():
        return "oidc"
    if _password_configured():
        return "password"
    return "none"


def _password_email_domains():
    domains = st.secrets.get("email_domains")
    return [d.lower().lstrip("@") for d in domains] if domains else None


def current_user_email():
    """The current identity's email, if known — else None.

    OIDC mode: comes from the verified identity token.
    Password mode: comes from what the person typed at login, only if
    email_domains is configured (otherwise there's no identity concept
    at all in password mode, and this returns None).

    None means "identity unknown" — callers should treat that as
    "can't verify who this is", not as "no one".
    """
    m = mode()
    if m == "oidc" and st.user.is_logged_in:
        email = st.user.get("email") or st.user.get("preferred_username") or ""
        return email.lower() or None
    if m == "password":
        return st.session_state.get("user_email")
    return None


def _allowed_tenant_id():
    return st.secrets.get("auth", {}).get("allowed_tenant_id")


def _allowed_email_domains():
    domains = st.secrets.get("auth", {}).get("allowed_email_domains")
    return [d.lower().lstrip("@") for d in domains] if domains else None


def _identity_allowed():
    """Backstop check, on top of whatever the IdP/app registration already
    enforces. Returns (allowed: bool, reason: str | None)."""
    tenant_id = _allowed_tenant_id()
    if tenant_id and st.user.get("tid") != tenant_id:
        return False, "This account isn't part of the expected organization."

    domains = _allowed_email_domains()
    if domains:
        email = (st.user.get("email") or st.user.get("preferred_username") or "").lower()
        if not any(email.endswith("@" + d) for d in domains):
            return False, f"Only {', '.join('@' + d for d in domains)} accounts can sign in."

    return True, None


def require_login():
    m = mode()

    if m == "oidc":
        if not st.user.is_logged_in:
            st.title("🗂️ Incident Vault")
            st.write("Sign in with your organization account to continue.")
            st.button("Log in", on_click=st.login, type="primary")
            st.stop()

        allowed, reason = _identity_allowed()
        if not allowed:
            st.title("🗂️ Incident Vault")
            st.error(reason)
            st.button("Log out", on_click=st.logout, type="primary")
            st.stop()

        with st.sidebar:
            label = st.user.get("email") or st.user.get("name") or "signed in"
            st.caption(f"Signed in as {label}")
            st.button("Log out", on_click=st.logout)
        return

    if m == "password":
        if not st.session_state.get("authed"):
            st.title("🗂️ Incident Vault")
            domains = _password_email_domains()

            email = ""
            if domains:
                email = st.text_input("Work email", placeholder=f"you@{domains[0]}")
            pw = st.text_input("Password", type="password")

            if st.button("Enter", type="primary"):
                if not (pw and pw == st.secrets["app_password"]):
                    st.error("Wrong password.")
                elif domains and not any(email.lower().endswith("@" + d) for d in domains):
                    st.error(f"Enter a {', '.join('@' + d for d in domains)} email to continue.")
                else:
                    st.session_state["authed"] = True
                    if domains:
                        st.session_state["user_email"] = email.lower()
                    st.rerun()
            st.stop()

        if st.session_state.get("user_email"):
            with st.sidebar:
                st.caption(f"Signed in as {st.session_state['user_email']}")
                if st.button("Log out"):
                    st.session_state.pop("authed", None)
                    st.session_state.pop("user_email", None)
                    st.rerun()
        return

    st.warning(
        "No authentication configured — anyone with this app's URL can view and edit "
        "everything. See README for how to add a password or sign-in.",
        icon="⚠️",
    )
