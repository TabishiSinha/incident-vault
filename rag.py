"""
Retrieval-augmented search over stored incident documents.

Provider is picked automatically from whichever secret is present —
GROQ_API_KEY is checked first since Groq is the default here, with
ANTHROPIC_API_KEY as an optional fallback. Override explicitly with:

    LLM_PROVIDER = "groq"        # or "anthropic"

Groq model note: Groq deprecates/renames models periodically. The default
below (openai/gpt-oss-120b) is the current general-purpose recommendation
as of mid-2026 — check console.groq.com/docs/models if search errors
mention a decommissioned model, and override via GROQ_MODEL in secrets.
"""

import streamlit as st

MAX_CONTEXT_CHARS = 14000
GROQ_MODEL = "openai/gpt-oss-120b"
ANTHROPIC_MODEL = "claude-sonnet-5"

SYSTEM_TEMPLATE = (
    "You are a retrieval assistant for an incident document vault. "
    "Answer the user's question using ONLY the incident documents provided below. "
    "If the answer isn't in the documents, say so plainly — do not invent details. "
    "Cite which document(s) you drew from by title. Keep the answer concise and structured.\n\n"
    "INCIDENT DOCUMENTS:\n{context}"
)


def _provider():
    explicit = st.secrets.get("LLM_PROVIDER")
    if explicit:
        return explicit
    if "GROQ_API_KEY" in st.secrets:
        return "groq"
    if "ANTHROPIC_API_KEY" in st.secrets:
        return "anthropic"
    return None


def api_key_configured():
    return _provider() is not None


def build_context(documents):
    context = ""
    included = []
    for d in documents:
        header = f"### {d['title']}" + (f" ({d['incident_id']})" if d.get("incident_id") else "")
        block = f"{header}\n{d['body']}\n\n"
        if len(context) + len(block) > MAX_CONTEXT_CHARS:
            break
        context += block
        included.append(d["title"])
    return context, included


def _search_groq(query, system_prompt):
    from groq import Groq

    client = Groq(api_key=st.secrets["GROQ_API_KEY"])
    resp = client.chat.completions.create(
        model=st.secrets.get("GROQ_MODEL", GROQ_MODEL),
        max_tokens=1000,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query},
        ],
    )
    return (resp.choices[0].message.content or "").strip()


def _search_anthropic(query, system_prompt):
    import anthropic

    client = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model=st.secrets.get("ANTHROPIC_MODEL", ANTHROPIC_MODEL),
        max_tokens=1000,
        system=system_prompt,
        messages=[{"role": "user", "content": query}],
    )
    return "\n".join(b.text for b in message.content if b.type == "text").strip()


def search(query, documents):
    if not documents:
        return None, [], "The vault is empty — store at least one document before searching."

    provider = _provider()
    if not provider:
        return None, [], "No LLM API key set in secrets (GROQ_API_KEY or ANTHROPIC_API_KEY) — search is disabled."

    context, included = build_context(documents)
    system_prompt = SYSTEM_TEMPLATE.format(context=context)

    try:
        if provider == "groq":
            text = _search_groq(query, system_prompt)
        elif provider == "anthropic":
            text = _search_anthropic(query, system_prompt)
        else:
            return None, [], f"Unknown LLM_PROVIDER '{provider}' — use 'groq' or 'anthropic'."
        return text or "(no answer returned)", included, None
    except Exception as e:
        return None, [], f"Search failed: {e}"
