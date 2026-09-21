import os
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

text_folder = os.path.join(BASE_DIR, "dataset", "text")
output_file = os.path.join(BASE_DIR, "dataset", "training_data.json")

# -------------------------
# SIMPLE LABELING RULES
# -------------------------

SKILLS = [
    "python","java","javascript","sql","aws","docker","kubernetes",
    "react","redux","typescript","spring","spring boot","microservices",
    "mongodb","mysql","postgresql","redis","langchain","rag","llm","embeddings"
]

def label_text(text):

    entities = []
    used_spans = []

    # NAME (first line)
    lines = text.split("\n")
    if lines:
        name = lines[0].strip()
        if len(name.split()) <= 4:
            start = text.find(name)
            end = start + len(name)
            entities.append((start, end, "NAME"))
            used_spans.append((start, end))

    lower_text = text.lower()

    for skill in SKILLS:

        start = 0
        while True:
            idx = lower_text.find(skill, start)

            if idx == -1:
                break

            end = idx + len(skill)

            # 🔥 CHECK OVERLAP
            overlap = False
            for s, e in used_spans:
                if not (end <= s or idx >= e):
                    overlap = True
                    break

            if not overlap:
                entities.append((idx, end, "SKILL"))
                used_spans.append((idx, end))

            start = end

    return entities


# -------------------------
# MAIN
# -------------------------

training_data = []

for file in os.listdir(text_folder):

    if not file.endswith(".txt"):
        continue

    file_path = os.path.join(text_folder, file)

    with open(file_path, encoding="utf-8") as f:
        text = f.read()

    entities = label_text(text)

    training_data.append({
        "text": text,
        "entities": entities
    })

# save
with open(output_file, "w", encoding="utf-8") as f:
    json.dump(training_data, f, indent=2)

print("✅ Training data created:", output_file)