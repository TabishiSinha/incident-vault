# Incident Vault - https://incident-vault-zlkb6bke6zbtmen4ybokxm.streamlit.app/

A document store, two-step approval tracker, and Groq-powered incident
search, built with Streamlit.

## Features

- **Documents** — paste text or upload `.txt` / `.pdf` / `.docx` files.
- **Approvals** — route a stored document to two approver emails; step 2 unlocks only after step 1 is approved, and (with SMTP configured) each approver gets an email when it's their turn.
- **Search** — ask a question and get an answer grounded only in your stored documents, via Groq (or Claude as a fallback).
- **Authentication** — a shared password gate, or real sign-in via Microsoft Entra ID (or any OIDC provider), which also restricts each approval step to the matching approver's actual identity.

Storage is pluggable: **local SQLite by default** (zero setup), or
**SharePoint** (a document library + two lists) once you add
`[sharepoint]` secrets — no code changes needed either way, see below.

## Run it locally

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# edit .streamlit/secrets.toml with your own GROQ_API_KEY etc.

streamlit run app.py
```

Open the URL Streamlit prints (usually `http://localhost:8501`).

All secrets are optional:
- Without `app_password` or `[auth]`, the app runs unauthenticated with a visible warning banner — fine for local testing, not for anything real.
- Without `GROQ_API_KEY` (or `ANTHROPIC_API_KEY`), the Search tab shows a warning and stays disabled.
- Without `[sharepoint]`, documents/approvals store in a local `vault.db` (SQLite).
- Without `[smtp]`, approvals still work — they just don't email approvers.

**Never commit `.streamlit/secrets.toml`** — it's already in `.gitignore`.

## Push to GitHub

```bash
git init
git add .
git commit -m "Incident Vault: documents, approvals, Groq-grounded search"
git branch -M main
git remote add origin https://github.com/<your-username>/incident-vault.git
git push -u origin main
```

(Create the empty repo on GitHub first — github.com → New repository — then
run the commands above from this folder.)

## Deploy on Streamlit Community Cloud

1. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub.
2. Click **New app**, pick the `incident-vault` repo, branch `main`, main file `app.py`.
3. Open **Settings → Secrets** on the app and paste the same content as
   `secrets.toml.example`, filled in with your real values.
4. Click **Deploy**. First build takes a couple of minutes.

## Search: switching between Groq and Claude

Search picks a provider automatically: `GROQ_API_KEY` is checked first, then
`ANTHROPIC_API_KEY` as a fallback. Force one explicitly with
`LLM_PROVIDER = "groq"` or `"anthropic"` in secrets.

Groq's model catalog changes more often than most providers — models get
renamed or retired every few months. The default here is
`openai/gpt-oss-120b` (a strong general-purpose model hosted on Groq's
infrastructure, not from OpenAI's own API). If search starts erroring about
a decommissioned model, check
[console.groq.com/docs/models](https://console.groq.com/docs/models) and
override with `GROQ_MODEL = "..."` in secrets.

## Authentication

Right now, without any secrets set, **anyone with the app's URL can view, add,
or delete documents, and approve or reject either step regardless of who
they are.** That's fine for local testing, not for anything with real
content. Two ways to close that, picked automatically from secrets:

### Option A: shared password (no IT dependency, works today)

```toml
app_password = "choose-a-password"
```

Everyone who opens the app has to enter this password once per session.
By itself, it doesn't know *who* is behind the browser — just that they
knew the password.

Add `email_domains` to also require a work email at login, restricted to
whatever domain(s) you list:

```toml
app_password = "choose-a-password"
email_domains = ["accenture.com"]
```

This makes the Approvals tab restrict each step's Approve/Reject to
whoever's declared email matches that step's approver — same behavior as
the OIDC option below. **The difference is verification**: this email is
self-declared, not cryptographically confirmed. Anyone who knows the
password can type any `@accenture.com`-looking address. It's a real
improvement over the plain password gate — a domain check at the door,
plus per-approver gating — but it is not the same guarantee as Option B.
Use it as the practical option while you're waiting on an Azure AD app
registration, not as a permanent substitute for one.

### Option B: real sign-in via Microsoft Entra ID (or any OIDC provider)

```toml
[auth]
redirect_uri = "http://localhost:8501/oauth2callback"   # your deployed URL + /oauth2callback, once deployed
cookie_secret = "generate-a-long-random-string-here"
client_id = "..."
client_secret = "..."
server_metadata_url = "https://login.microsoftonline.com/<tenant_id>/v2.0/.well-known/openid-configuration"
```

This uses Streamlit's built-in `st.login()` (OIDC). Once it's set, people
sign in with their real organization account, and the Approvals tab
automatically restricts each step's Approve/Reject buttons to whoever's
email matches that step's approver — no one else can act on it, even with
the app's URL.

**What to ask your IT/Azure admin for** — a *second* app registration
alongside the SharePoint one from below (they're different kinds: this one
signs users in, the SharePoint one calls Graph API on the app's own
behalf):

1. An **App registration** in Azure AD (Entra ID) configured for user
   sign-in, with a **redirect URI** of `<your-app-url>/oauth2callback`
   (use `http://localhost:8501/oauth2callback` while testing locally).
2. Set to **"Accounts in this organizational directory only"** (single
   tenant) — this is what actually restricts sign-in to Accenture accounts.
   Microsoft rejects outside accounts before the app ever sees them; it's
   not something to bolt on afterward in code.
3. A **client secret** for it.
4. Confirmation of your **tenant ID**.

Put those into the `[auth]` block above. `cookie_secret` is not from
Azure — generate any long random string yourself, e.g. with
`python -c "import secrets; print(secrets.token_hex(32))"`.

**Belt and suspenders:** even with a single-tenant registration, you can
add an in-app check as a backstop (e.g. in case the registration is ever
accidentally changed to multi-tenant):

```toml
[auth]
# ...same as above, plus:
allowed_tenant_id = "..."                  # your Entra ID tenant GUID
allowed_email_domains = ["accenture.com"]
```

Either or both — `allowed_tenant_id` checks the cryptographically-signed
tenant claim in the identity token; `allowed_email_domains` checks the
email suffix. If someone signs in with an account that fails the check,
they see a blocked screen instead of the app.

## Switching storage to SharePoint

SharePoint isn't a drop-in like Groq — it needs an Azure AD app
registration your org's IT/identity team sets up. Once that's in place,
turning it on is just adding secrets; no code changes.

**What to ask your IT/Azure admin for:**

1. An **App registration** in Azure AD (Entra ID), with a client secret.
2. **Microsoft Graph API permissions**, admin-consented. Two options:
   - `Sites.Selected` (recommended) — scoped to just your one SharePoint
     site. Ask your admin to grant this app **write** access to the
     specific site via the Graph `/sites/{id}/permissions` endpoint or
     SharePoint PnP PowerShell. This is the easier ask for IT to approve
     in a bank environment since it can't touch any other site.
   - `Sites.ReadWrite.All` — tenant-wide access to all SharePoint sites.
     Simpler to set up but a much bigger ask; expect more scrutiny.
3. The **tenant ID**, **client ID**, and **client secret** from that
   registration, plus your **site URL** (e.g.
   `https://yourtenant.sharepoint.com/sites/YourSite`).

**Then in secrets** (locally or in Streamlit Cloud), uncomment and fill in:

```toml
[sharepoint]
tenant_id = "..."
client_id = "..."
client_secret = "..."
site_url = "https://yourtenant.sharepoint.com/sites/YourSite"
docs_list = "IncidentDocuments"        # optional, this is the default
approvals_list = "IncidentApprovals"   # optional, this is the default
```

On first run, the app automatically creates the two SharePoint Lists
(`IncidentDocuments`, `IncidentApprovals`) with the columns they need, and
uploads files into an `IncidentVault/` folder in the site's default
document library. Nothing to pre-create by hand.

**A data-handling note:** once this points at a real SharePoint site, this
app is moving real content between a public cloud host (Streamlit
Community Cloud), a third-party inference API (Groq or Anthropic), and
your corporate SharePoint. Worth a quick check against your org's data
governance policy before pointing it at anything beyond synthetic/demo
incident data — especially in a bank environment. Authentication (above)
closes the "anyone with the URL" gap; it doesn't cover encryption at rest,
audit logging of who approved what, or removing SQLite as a fallback if
SharePoint isn't configured — worth knowing if this ever moves past a
personal prototype.

## Project structure

```
app.py             Streamlit UI — three tabs (Documents / Approvals / Search)
auth.py             Password gate or Microsoft Entra ID (OIDC) sign-in
storage.py          Picks SQLite or SharePoint backend based on secrets
db.py               SQLite storage backend (default)
sharepoint.py        SharePoint storage backend (Microsoft Graph API)
file_extract.py     Text extraction from uploaded .txt/.pdf/.docx
email_utils.py      Optional SMTP notifications for approval steps
rag.py              Retrieval-augmented search via Groq or Claude
requirements.txt
.streamlit/secrets.toml.example   Template — copy, don't commit the real one
```
