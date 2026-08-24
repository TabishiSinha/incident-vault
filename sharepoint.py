"""
SharePoint-backed storage for Incident Vault, via Microsoft Graph API.

Requires an Azure AD app registration with Graph permissions
(Sites.ReadWrite.All, tenant-wide, or the narrower Sites.Selected scoped to
just your site) and admin consent — your org's IT/identity team sets this
up, not this app. See README.md for the full walkthrough.

Secrets expected:

    [sharepoint]
    tenant_id = "..."
    client_id = "..."
    client_secret = "..."
    site_url = "https://yourtenant.sharepoint.com/sites/YourSite"
    doc_library = "Documents"          # optional, default document library
    docs_list = "IncidentDocuments"    # created automatically if missing
    approvals_list = "IncidentApprovals"

The two SharePoint Lists (docs_list, approvals_list) and the drive folder
they point to are created automatically the first time the app runs, if
they don't already exist — no manual list setup required, just the app
registration and permissions.
"""

import datetime as dt
import time
from urllib.parse import urlparse

import requests
import streamlit as st

GRAPH = "https://graph.microsoft.com/v1.0"

DOCS_COLUMNS = [
    {"name": "IncidentID", "text": {}},
    {"name": "Body", "text": {"allowMultipleLines": True, "linesForEditing": 12}},
    {"name": "FileUrl", "text": {}},
]
APPROVALS_COLUMNS = [
    {"name": "DocId", "text": {}},
    {"name": "DocTitle", "text": {}},
    {"name": "Approver1Email", "text": {}},
    {"name": "Approver2Email", "text": {}},
    {"name": "Step1Status", "text": {}},
    {"name": "Step2Status", "text": {}},
]


def _cfg():
    return st.secrets["sharepoint"]


@st.cache_resource(show_spinner=False)
def _token_cache():
    return {"access_token": None, "expires_at": 0}


def _get_token():
    cache = _token_cache()
    if cache["access_token"] and cache["expires_at"] > time.time() + 60:
        return cache["access_token"]

    cfg = _cfg()
    url = f"https://login.microsoftonline.com/{cfg['tenant_id']}/oauth2/v2.0/token"
    resp = requests.post(
        url,
        data={
            "grant_type": "client_credentials",
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "scope": "https://graph.microsoft.com/.default",
        },
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    cache["access_token"] = data["access_token"]
    cache["expires_at"] = time.time() + data.get("expires_in", 3600)
    return cache["access_token"]


def _graph(method, path, extra_headers=None, **kwargs):
    headers = {"Authorization": f"Bearer {_get_token()}"}
    if extra_headers:
        headers.update(extra_headers)
    else:
        headers["Content-Type"] = "application/json"
    resp = requests.request(method, f"{GRAPH}{path}", headers=headers, timeout=30, **kwargs)
    if resp.status_code >= 400:
        raise RuntimeError(f"Graph API {method} {path} failed: {resp.status_code} {resp.text[:400]}")
    return resp


@st.cache_resource(show_spinner=False)
def _site_id():
    site_url = _cfg()["site_url"]
    parsed = urlparse(site_url)
    resp = _graph("GET", f"/sites/{parsed.netloc}:{parsed.path}")
    return resp.json()["id"]


def _find_or_create_list(list_name, columns):
    site_id = _site_id()
    resp = _graph("GET", f"/sites/{site_id}/lists?$filter=displayName eq '{list_name}'")
    items = resp.json().get("value", [])
    if items:
        return items[0]["id"]
    body = {"displayName": list_name, "list": {"template": "genericList"}, "columns": columns}
    resp = _graph("POST", f"/sites/{site_id}/lists", json=body)
    return resp.json()["id"]


@st.cache_resource(show_spinner=False)
def _docs_list_id():
    return _find_or_create_list(_cfg().get("docs_list", "IncidentDocuments"), DOCS_COLUMNS)


@st.cache_resource(show_spinner=False)
def _approvals_list_id():
    return _find_or_create_list(_cfg().get("approvals_list", "IncidentApprovals"), APPROVALS_COLUMNS)


@st.cache_resource(show_spinner=False)
def _drive_id():
    site_id = _site_id()
    resp = _graph("GET", f"/sites/{site_id}/drive")
    return resp.json()["id"]


def _parse_iso(ts):
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


def init_db():
    # Resolve/create everything up front so setup problems surface immediately
    # with a clear error, instead of failing later mid-workflow.
    _docs_list_id()
    _approvals_list_id()
    _drive_id()


# --- documents -----------------------------------------------------------

def add_document(title, incident_id, body, upload_bytes=None, upload_filename=None):
    file_url = ""
    if upload_bytes and upload_filename:
        drive_id = _drive_id()
        path = f"IncidentVault/{upload_filename}"
        resp = _graph(
            "PUT",
            f"/drives/{drive_id}/root:/{path}:/content",
            extra_headers={"Content-Type": "application/octet-stream"},
            data=upload_bytes,
        )
        file_url = resp.json().get("webUrl", "")

    site_id = _site_id()
    list_id = _docs_list_id()
    fields = {"Title": title, "IncidentID": incident_id, "Body": body, "FileUrl": file_url}
    resp = _graph("POST", f"/sites/{site_id}/lists/{list_id}/items", json={"fields": fields})
    return resp.json()["id"]


def get_documents():
    site_id = _site_id()
    list_id = _docs_list_id()
    resp = _graph(
        "GET",
        f"/sites/{site_id}/lists/{list_id}/items?$expand=fields&$orderby=createdDateTime desc&$top=200",
    )
    out = []
    for item in resp.json().get("value", []):
        f = item.get("fields", {})
        out.append(
            {
                "id": item["id"],
                "title": f.get("Title", ""),
                "incident_id": f.get("IncidentID", ""),
                "body": f.get("Body", ""),
                "file_url": f.get("FileUrl") or None,
                "created_at": _parse_iso(item["createdDateTime"]),
            }
        )
    return out


def delete_document(doc_id):
    site_id = _site_id()
    list_id = _docs_list_id()
    _graph("DELETE", f"/sites/{site_id}/lists/{list_id}/items/{doc_id}")


# --- approvals -------------------------------------------------------------

def start_approval(doc_id, doc_title, approver1_email, approver2_email):
    site_id = _site_id()
    list_id = _approvals_list_id()
    fields = {
        "Title": doc_title,
        "DocId": doc_id or "",
        "DocTitle": doc_title,
        "Approver1Email": approver1_email,
        "Approver2Email": approver2_email,
        "Step1Status": "pending",
        "Step2Status": "waiting",
    }
    resp = _graph("POST", f"/sites/{site_id}/lists/{list_id}/items", json={"fields": fields})
    return resp.json()["id"]


def get_approvals():
    site_id = _site_id()
    list_id = _approvals_list_id()
    resp = _graph(
        "GET",
        f"/sites/{site_id}/lists/{list_id}/items?$expand=fields&$orderby=createdDateTime desc&$top=200",
    )
    out = []
    for item in resp.json().get("value", []):
        f = item.get("fields", {})
        out.append(
            {
                "id": item["id"],
                "doc_id": f.get("DocId", ""),
                "doc_title": f.get("DocTitle", ""),
                "approver1_email": f.get("Approver1Email", ""),
                "approver2_email": f.get("Approver2Email", ""),
                "step1_status": f.get("Step1Status", "pending"),
                "step2_status": f.get("Step2Status", "waiting"),
                "created_at": _parse_iso(item["createdDateTime"]),
            }
        )
    return out


def update_approval_step(approval_id, step, decision):
    site_id = _site_id()
    list_id = _approvals_list_id()
    if step == 1:
        fields = {"Step1Status": decision, "Step2Status": "pending" if decision == "approved" else "waiting"}
    else:
        fields = {"Step2Status": decision}
    _graph("PATCH", f"/sites/{site_id}/lists/{list_id}/items/{approval_id}/fields", json=fields)


def delete_approval(approval_id):
    site_id = _site_id()
    list_id = _approvals_list_id()
    _graph("DELETE", f"/sites/{site_id}/lists/{list_id}/items/{approval_id}")
