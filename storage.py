"""
Storage router. Picks the SharePoint backend if [sharepoint] secrets are
present, otherwise falls back to local SQLite. Both backends expose the
exact same function names, so the rest of the app never needs to know
which one is active.
"""

import streamlit as st

if "sharepoint" in st.secrets:
    from sharepoint import (
        init_db,
        add_document,
        get_documents,
        delete_document,
        start_approval,
        get_approvals,
        update_approval_step,
        delete_approval,
    )

    BACKEND_NAME = "SharePoint"
else:
    from db import (
        init_db,
        add_document,
        get_documents,
        delete_document,
        start_approval,
        get_approvals,
        update_approval_step,
        delete_approval,
    )

    BACKEND_NAME = "SQLite (local)"
