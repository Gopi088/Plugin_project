import os
import json
import re

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

text_folder = os.path.join(BASE_DIR, "dataset", "text")
output_file = os.path.join(BASE_DIR, "dataset", "annotations.json")

annotations = []

email_regex = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
phone_regex = r"\+?\d[\d -]{8,12}\d"

skills_list = [
    "python","java","sql","machine learning","deep learning",
    "javascript","react","node","aws","docker","kubernetes",
    "pandas","numpy","tensorflow","pytorch"
]

for file in os.listdir(text_folder):

    if not file.endswith(".txt"):
        continue

    path = os.path.join(text_folder, file)

    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    entities = []

    # EMAIL
    for match in re.finditer(email_regex, text):
        entities.append([match.start(), match.end(), "EMAIL"])

    # PHONE
    for match in re.finditer(phone_regex, text):
        entities.append([match.start(), match.end(), "PHONE"])

    # SKILLS
    lower_text = text.lower()

    for skill in skills_list:

        start = lower_text.find(skill)

        if start != -1:
            end = start + len(skill)
            entities.append([start, end, "SKILL"])

    if entities:
        annotations.append({
            "text": text,
            "entities": entities
        })

print("Annotated resumes:", len(annotations))

with open(output_file, "w", encoding="utf-8") as f:
    json.dump(annotations, f, indent=2)

print("annotations.json created")
