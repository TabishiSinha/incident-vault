"""
Optional email notifications for the approval workflow.

Reads SMTP settings from Streamlit secrets (.streamlit/secrets.toml locally,
or the Secrets panel on Streamlit Community Cloud). If those secrets aren't
set, email sending is silently skipped — the approval workflow still works,
it just won't notify anyone by email.

Expected secrets:
    [smtp]
    host = "smtp.gmail.com"
    port = 587
    username = "you@example.com"
    password = "an app password, not your account password"
    from_addr = "you@example.com"
"""

import smtplib
from email.mime.text import MIMEText

import streamlit as st


def email_configured():
    return "smtp" in st.secrets


def send_notification(to_email, subject, body):
    if not email_configured():
        return False, "SMTP not configured — skipped sending."

    cfg = st.secrets["smtp"]
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = cfg["from_addr"]
    msg["To"] = to_email

    try:
        with smtplib.SMTP(cfg["host"], int(cfg["port"])) as server:
            server.starttls()
            server.login(cfg["username"], cfg["password"])
            server.sendmail(cfg["from_addr"], [to_email], msg.as_string())
        return True, "sent"
    except Exception as e:
        return False, str(e)
