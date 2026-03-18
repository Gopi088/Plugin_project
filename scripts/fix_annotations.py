import re
import json

SKILLS = [
    "python", "java", "sql", "aws", "gcp", "azure",
    "docker", "kubernetes", "react", "mongodb",
    "postgresql", "tableau", "power bi", "spark",
    "hadoop", "airflow", "snowflake", "bigquery",
    "langchain", "rag", "llm"
]

def fix_annotations(data):

    fixed_data = []

    for item in data:
        text = item["text"]
        entities = []

        # NAME → first line
        first_line = text.split("\n")[0].strip()
        start = text.find(first_line)
        end = start + len(first_line)

        if len(first_line.split()) <= 5:
            entities.append([start, end, "NAME"])

        # EMAIL
        for match in re.finditer(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text):
            entities.append([match.start(), match.end(), "EMAIL"])

        # PHONE
        for match in re.finditer(r"\+?\d{10,15}", text):
            entities.append([match.start(), match.end(), "PHONE"])

        # SKILLS
        lower_text = text.lower()

        for skill in SKILLS:
            for match in re.finditer(skill, lower_text):
                entities.append([match.start(), match.end(), "SKILL"])

        fixed_data.append({
            "text": text,
            "entities": entities
        })

    return fixed_data


# LOAD + SAVE
with open("dataset/annotations.json", "r") as f:
    data = json.load(f)

fixed = fix_annotations(data)

with open("dataset/fixed_annotations.json", "w") as f:
    json.dump(fixed, f, indent=2)

print("✅ Fixed annotations saved!")