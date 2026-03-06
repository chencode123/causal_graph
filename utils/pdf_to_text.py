import pdfplumber
import re

def pdf_to_text(path):
    pages = []

    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            
            text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)

            pages.append(text.strip())

    return "\n\n".join(pages)
