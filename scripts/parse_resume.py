import spacy
import os
import re
from pdfminer.high_level import extract_text
from docx import Document

# -------------------------
# LOAD MODEL
# -------------------------

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
model_path = os.path.join(BASE_DIR, "model")

nlp = spacy.load(model_path)

# -------------------------
# REGEX
# -------------------------

email_regex = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
phone_regex = r"\+?\d[\d -]{8,12}\d"
linkedin_regex = r"(linkedin\.com/in/[A-Za-z0-9_-]+)"
github_regex = r"(github\.com/[A-Za-z0-9_-]+)"

# -------------------------
# DOCX EXTRACTOR
# -------------------------

def extract_text_from_docx(file_path):
    doc = Document(file_path)
    return "\n".join([para.text for para in doc.paragraphs])

# -------------------------
# MAIN PARSER
# -------------------------

def parse_resume(file_path):

    # 🔥 HANDLE FILE TYPES
    if file_path.endswith(".pdf"):
        text = extract_text(file_path)

    elif file_path.endswith(".docx"):
        text = extract_text_from_docx(file_path)

    else:
        with open(file_path, encoding="utf-8") as f:
            text = f.read()

    doc = nlp(text)

    profile = {
        "name": None,
        "email": None,
        "phone": None,
        "linkedin": None,
        "github": None,
        "skills": []
    }

    # -------------------------
    # CONTACT INFO
    # -------------------------

    email = re.findall(email_regex, text)
    phone = re.findall(phone_regex, text)
    linkedin = re.findall(linkedin_regex, text)
    github = re.findall(github_regex, text)

    if email:
        profile["email"] = email[0]

    if phone:
        profile["phone"] = phone[0]

    if linkedin:
        profile["linkedin"] = linkedin[0]

    if github:
        profile["github"] = github[0]

    # -------------------------
    # NER EXTRACTION
    # -------------------------

    for ent in doc.ents:

        if ent.label_ == "NAME":
            profile["name"] = ent.text

        elif ent.label_ == "SKILL":
            profile["skills"].append(ent.text)

    # remove duplicates
    profile["skills"] = list(set(profile["skills"]))

    return profile