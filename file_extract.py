"""Extract plain text from uploaded documents (.txt, .pdf, .docx)."""

import io


def extract_text(filename, data: bytes) -> str:
    name = filename.lower()

    if name.endswith(".txt"):
        return data.decode("utf-8", errors="ignore")

    if name.endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages).strip()

    if name.endswith(".docx"):
        import docx

        d = docx.Document(io.BytesIO(data))
        return "\n".join(p.text for p in d.paragraphs).strip()

    raise ValueError(f"Unsupported file type: {filename}")
