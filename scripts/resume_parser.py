import spacy
import re
import pdfplumber

nlp = spacy.load("model")

# -------------------------
# REGEX
# -------------------------

email_regex = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
phone_regex = r"\+?\d{10,15}"

# -------------------------
# VALID SKILLS
# -------------------------

VALID_SKILLS = [
    "python", "java", "javascript", "sql",
    "aws", "docker", "kubernetes",
    "react", "redux", "typescript",
    "spring", "spring boot", "microservices",
    "mongodb", "mysql", "postgresql", "redis",
    "langchain", "rag", "llm", "embeddings",
    "kafka", "hadoop", "spark", "airflow",
    "fastapi", "django", "flask",
    "node.js", "express.js"
]

# -------------------------
# PDF TEXT EXTRACTION
# -------------------------

def extract_text_from_pdf(file_path):
    text = ""
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text

# -------------------------
# CLEAN TEXT
# -------------------------

def clean_text(text):
    text = text.replace("\u2022", "•")
    text = text.replace("\u2013", "-")
    text = text.replace("\u2014", "-")

    # fix broken words
    text = re.sub(r'(\w)-\s+(\w)', r'\1\2', text)

    return text.strip()

# -------------------------
# NAME
# -------------------------

def extract_name(raw_text):
    lines = [l.strip() for l in raw_text.split("\n") if l.strip()]

    for line in lines[:10]:
        if any(x in line.lower() for x in ["@", "linkedin", "github", "india"]):
            continue

        if 2 <= len(line.split()) <= 4 and line.replace(" ", "").isalpha():
            return line.upper()

    return None

# -------------------------
# SUMMARY
# -------------------------

def extract_summary(text):
    match = re.search(
        r"(summary|professional summary)(.*?)(skills|technical|experience)",
        text,
        re.IGNORECASE | re.DOTALL
    )
    return match.group(2).strip()[:500] if match else ""

# -------------------------
# SKILLS
# -------------------------

def extract_skills(doc, text):

    skills = set()

    for ent in doc.ents:
        if ent.label_ == "SKILL":
            skill = ent.text.lower()
            if skill in VALID_SKILLS:
                skills.add(skill.title())

    for skill in VALID_SKILLS:
        if skill in text.lower():
            skills.add(skill.title())

    return list(skills)

# -------------------------
# EXPERIENCE (FINAL FIXED)
# -------------------------

def extract_experience(raw_text):

    experience = []

    text = raw_text.replace("–", "-").replace("—", "-")

    match = re.search(
        r"(PROFESSIONAL EXPERIENCE|EXPERIENCE)(.*?)(KEY PROJECTS|EDUCATION|$)",
        text,
        re.IGNORECASE | re.DOTALL
    )

    if not match:
        return experience

    section = match.group(2)

    lines = [l.strip() for l in section.split("\n") if l.strip()]

    current_job = None

    for i, line in enumerate(lines):

        if "experience" in line.lower():
            continue

        # ✅ STRICT DATE MATCH
        date_match = re.search(
            r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)?\s*\d{4}\s*-\s*(Present|\d{4})",
            line
        )

        if date_match:

            if current_job:
                experience.append(current_job)

            # 🔥 KEY FIX (POSITION BASED)
            role = line[:date_match.start()].strip(" -–")
            duration = line[date_match.start():].strip()

            company = ""
            if i + 1 < len(lines):
                company = lines[i + 1]

            current_job = {
                "role": role,
                "company": company,
                "duration": duration,
                "details": []
            }

        elif line.startswith("•"):

            if current_job:
                current_job["details"].append(
                    line.replace("•", "").strip()
                )

        elif current_job and current_job["details"]:
            current_job["details"][-1] += " " + line

    if current_job:
        experience.append(current_job)

    return experience

# -------------------------
# PROJECTS
# -------------------------

def extract_projects(raw_text):

    projects = []

    text = raw_text.replace("–", "-").replace("—", "-")

    match = re.search(
        r"(KEY PROJECTS|Projects)(.*?)(EDUCATION|$)",
        text,
        re.IGNORECASE | re.DOTALL
    )

    if not match:
        return projects

    section = match.group(2)

    lines = [l.strip() for l in section.split("\n") if l.strip()]

    current_project = None

    for line in lines:

        if line.upper() in ["KEY PROJECTS", "PROJECTS"]:
            continue

        if (
            not line.startswith("•")
            and len(line.split()) <= 6
            and line[0].isupper()
            and not line.endswith(".")
        ):

            if current_project:
                projects.append(current_project)

            current_project = {
                "name": line,
                "details": []
            }

        elif line.startswith("•"):

            if current_project:
                current_project["details"].append(
                    line.replace("•", "").strip()
                )

        elif current_project and current_project["details"]:
            current_project["details"][-1] += " " + line

    if current_project:
        projects.append(current_project)

    return projects

# -------------------------
# MAIN
# -------------------------

def parse_resume(file_path):

    raw_text = extract_text_from_pdf(file_path)
    text = clean_text(raw_text)

    doc = nlp(text)

    profile = {
        "name": extract_name(raw_text),
        "email": None,
        "phone": None,
        "summary": extract_summary(text),
        "skills": extract_skills(doc, text),
        "experience": extract_experience(raw_text),
        "education": [],
        "projects": extract_projects(raw_text),
        "certifications": [],
        "links": []
    }

    email = re.findall(email_regex, text)
    phone = re.findall(phone_regex, text)

    if email:
        profile["email"] = email[0]

    if phone:
        profile["phone"] = phone[0]

    if "bachelor" in text.lower():
        profile["education"].append({
            "degree": "Bachelor of Technology",
            "institution": "",
            "year": ""
        })

    return profile