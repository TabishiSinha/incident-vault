import datetime as dt

import streamlit as st

import storage as db
import auth
import email_utils
import rag
from file_extract import extract_text

st.set_page_config(page_title="Incident Vault", page_icon="🗂️", layout="wide")
auth.require_login()
db.init_db()

# ---------------------------------------------------------------------------
# Styling — dark ops-console look, matching the original prototype
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    .stApp { background-color: #10141A; color: #E5E9EE; }
    section[data-testid="stSidebar"] { background-color: #171D25; }
    .pill {
        display: inline-flex; align-items: center; gap: 5px;
        font-family: monospace; font-size: 11px; font-weight: 700;
        letter-spacing: 0.05em; padding: 3px 9px; border-radius: 20px;
    }
    .pill-pending  { background: rgba(232,163,61,0.16); color: #E8A33D; }
    .pill-approved { background: rgba(79,182,168,0.16); color: #4FB6A8; }
    .pill-rejected { background: rgba(224,107,88,0.16); color: #E06B58; }
    .pill-waiting  { background: rgba(137,146,160,0.14); color: #8992A0; }
    .mono-tag {
        font-family: monospace; font-size: 11px;
        background: rgba(110,147,214,0.14); color: #6E93D6;
        padding: 2px 7px; border-radius: 3px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def status_pill(status):
    labels = {
        "pending": ("PENDING", "pill-pending"),
        "approved": ("APPROVED", "pill-approved"),
        "rejected": ("REJECTED", "pill-rejected"),
        "waiting": ("WAITING", "pill-waiting"),
    }
    label, cls = labels.get(status, labels["pending"])
    return f'<span class="pill {cls}">{label}</span>'


def fmt_time(ts):
    return dt.datetime.fromtimestamp(ts).strftime("%b %d, %H:%M")


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
docs = db.get_documents()
approvals = db.get_approvals()

pending_count = sum(
    1 for a in approvals if a["step1_status"] == "pending" or (a["step1_status"] == "approved" and a["step2_status"] == "pending")
)
resolved_count = sum(
    1 for a in approvals if a["step2_status"] == "approved" or a["step1_status"] == "rejected" or a["step2_status"] == "rejected"
)

st.markdown("## 🗂️ Incident Vault")
st.caption(f"document store ({db.BACKEND_NAME}) · two-step approval log · Groq-grounded search")

c1, c2, c3 = st.columns(3)
c1.metric("Documents", len(docs))
c2.metric("Pending approvals", pending_count)
c3.metric("Resolved", resolved_count)

st.divider()

tab_docs, tab_approvals, tab_search = st.tabs(["📄 Documents", "🛡️ Approvals", "🔎 Search"])

# ---------------------------------------------------------------------------
# Documents tab
# ---------------------------------------------------------------------------
with tab_docs:
    left, right = st.columns(2)

    with left:
        st.subheader("Store a document")
        st.caption("Paste text directly, or upload a .txt / .pdf / .docx file to extract its content.")

        upload = st.file_uploader("Upload a file (optional)", type=["txt", "pdf", "docx"])
        prefill_body = ""
        prefill_title = ""
        upload_bytes = None
        upload_filename = None
        if upload is not None:
            upload_bytes = upload.getvalue()
            upload_filename = upload.name
            try:
                prefill_body = extract_text(upload.name, upload_bytes)
                prefill_title = upload.name.rsplit(".", 1)[0]
                st.success(f"Extracted {len(prefill_body)} characters from {upload.name}.")
                if db.BACKEND_NAME.startswith("SharePoint"):
                    st.caption("The original file will also be uploaded to your SharePoint document library.")
            except Exception as e:
                st.error(f"Couldn't read that file: {e}")

        with st.form("add_doc_form", clear_on_submit=True):
            title = st.text_input("Title", value=prefill_title, placeholder="e.g. Kerberos keytab expiry — Murex to SAP")
            incident_id = st.text_input("Incident ID (optional)", placeholder="e.g. INC0888742")
            body = st.text_area("Content", value=prefill_body, height=220, placeholder="Paste the RCA / PIR / narrative text here…")
            submitted = st.form_submit_button("Store document", type="primary")
            if submitted:
                if not title.strip() or not body.strip():
                    st.error("Give the document a title and some content before storing it.")
                else:
                    db.add_document(
                        title.strip(),
                        incident_id.strip(),
                        body.strip(),
                        upload_bytes=upload_bytes,
                        upload_filename=upload_filename,
                    )
                    st.rerun()

    with right:
        st.subheader("Stored documents")
        if not docs:
            st.info("Nothing stored yet. Add a document on the left to start building the vault.")
        else:
            for d in docs:
                with st.container(border=True):
                    top = st.columns([5, 1])
                    top[0].markdown(f"**{d['title']}**")
                    if top[1].button("🗑️", key=f"del_doc_{d['id']}", help="Delete"):
                        db.delete_document(d["id"])
                        st.rerun()
                    meta = f"<span class='mono-tag'>{d['incident_id']}</span> " if d["incident_id"] else ""
                    st.markdown(f"{meta}<span style='color:#8992A0;font-size:12px'>{fmt_time(d['created_at'])}</span>", unsafe_allow_html=True)
                    snippet = d["body"][:220] + ("…" if len(d["body"]) > 220 else "")
                    st.caption(snippet)
                    if d.get("file_url"):
                        st.markdown(f"[View original file]({d['file_url']})")

# ---------------------------------------------------------------------------
# Approvals tab
# ---------------------------------------------------------------------------
with tab_approvals:
    left, right = st.columns(2)

    with left:
        st.subheader("Start a two-step approval")
        if not email_utils.email_configured():
            st.warning("SMTP isn't configured in secrets, so approvers won't get real emails — status still tracks fine.")

        with st.form("start_approval_form", clear_on_submit=True):
            doc_options = {f"{d['title']}" + (f" — {d['incident_id']}" if d["incident_id"] else ""): d for d in docs}
            choice = st.selectbox("Document", ["Select a stored document…"] + list(doc_options.keys()))
            approver1 = st.text_input("Approver 1 email", placeholder="approver1@bankofireland.com")
            approver2 = st.text_input("Approver 2 email", placeholder="approver2@bankofireland.com")
            submitted = st.form_submit_button("Start approval", type="primary")
            if submitted:
                if choice == "Select a stored document…":
                    st.error("Pick a document to route for approval.")
                elif "@" not in approver1 or "@" not in approver2:
                    st.error("Enter a valid email for both approvers.")
                else:
                    d = doc_options[choice]
                    db.start_approval(d["id"], d["title"], approver1.strip(), approver2.strip())
                    ok, msg = email_utils.send_notification(
                        approver1.strip(),
                        f"Approval requested: {d['title']}",
                        f"You've been asked to review and approve: {d['title']}\n\n{d['body'][:1500]}",
                    )
                    st.rerun()

    with right:
        st.subheader("Approval log")
        if not approvals:
            st.info("No approvals started yet. Route a document on the left.")
        else:
            for a in approvals:
                with st.container(border=True):
                    top = st.columns([5, 1])
                    top[0].markdown(f"**{a['doc_title']}**")
                    if top[1].button("🗑️", key=f"del_appr_{a['id']}", help="Delete"):
                        db.delete_approval(a["id"])
                        st.rerun()

                    # Step 1
                    s1c = st.columns([3, 2, 2])
                    s1c[0].markdown(f"<span class='mono-tag'>STEP 1</span> {a['approver1_email']}", unsafe_allow_html=True)
                    s1c[1].markdown(status_pill(a["step1_status"]), unsafe_allow_html=True)
                    if a["step1_status"] == "pending":
                        current_email = auth.current_user_email()
                        can_act = current_email is None or current_email == a["approver1_email"].lower()
                        if not can_act:
                            s1c[2].caption(f"Only {a['approver1_email']} can act on this step")
                        else:
                            b1, b2 = s1c[2].columns(2)
                            if b1.button("Approve", key=f"s1_ok_{a['id']}"):
                                db.update_approval_step(a["id"], 1, "approved")
                                email_utils.send_notification(
                                    a["approver2_email"],
                                    f"Your approval needed: {a['doc_title']}",
                                    f"{a['approver1_email']} approved step 1 of \"{a['doc_title']}\". "
                                    f"It's now waiting on your approval as step 2.",
                                )
                                st.rerun()
                            if b2.button("Reject", key=f"s1_no_{a['id']}"):
                                db.update_approval_step(a["id"], 1, "rejected")
                                st.rerun()

                    # Step 2
                    s2c = st.columns([3, 2, 2])
                    s2c[0].markdown(f"<span class='mono-tag'>STEP 2</span> {a['approver2_email']}", unsafe_allow_html=True)
                    s2c[1].markdown(status_pill(a["step2_status"]), unsafe_allow_html=True)
                    if a["step2_status"] == "pending":
                        current_email = auth.current_user_email()
                        can_act = current_email is None or current_email == a["approver2_email"].lower()
                        if not can_act:
                            s2c[2].caption(f"Only {a['approver2_email']} can act on this step")
                        else:
                            b1, b2 = s2c[2].columns(2)
                            if b1.button("Approve", key=f"s2_ok_{a['id']}"):
                                db.update_approval_step(a["id"], 2, "approved")
                                st.rerun()
                            if b2.button("Reject", key=f"s2_no_{a['id']}"):
                                db.update_approval_step(a["id"], 2, "rejected")
                                st.rerun()

# ---------------------------------------------------------------------------
# Search tab
# ---------------------------------------------------------------------------
with tab_search:
    st.subheader("Ask the vault")
    st.caption("Answers are grounded only in documents you've stored — nothing else.")

    if not rag.api_key_configured():
        st.warning("No LLM API key set in secrets (GROQ_API_KEY or ANTHROPIC_API_KEY) — add one to enable search.")

    query = st.text_input("Question", placeholder="e.g. What caused the Murex to SAP file transfer failure?")
    if st.button("Search", type="primary") and query.strip():
        with st.spinner(f"Searching {len(docs)} document(s)…"):
            answer, sources, error = rag.search(query.strip(), docs)
        if error:
            st.error(error)
        else:
            st.markdown("**Result**")
            st.write(answer)
            if sources:
                st.caption("Searched: " + ", ".join(sources))
