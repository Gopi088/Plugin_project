import spacy
import json
import random
from spacy.training import Example
import os

# -------------------------
# PATHS
# -------------------------

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

data_path = os.path.join(BASE_DIR, "dataset", "training_data.json")
model_output = os.path.join(BASE_DIR, "model")

# -------------------------
# LOAD DATA
# -------------------------

with open(data_path, "r", encoding="utf-8") as f:
    data = json.load(f)

# -------------------------
# CONVERT TO SPACY FORMAT
# -------------------------

TRAIN_DATA = []

for item in data:
    text = item["text"]
    entities = item["entities"]

    TRAIN_DATA.append((text, {"entities": entities}))

# -------------------------
# CREATE MODEL
# -------------------------

nlp = spacy.blank("en")

ner = nlp.add_pipe("ner")

# Add labels
for _, annotations in TRAIN_DATA:
    for ent in annotations["entities"]:
        ner.add_label(ent[2])

# -------------------------
# TRAINING
# -------------------------

optimizer = nlp.begin_training()

for epoch in range(15):
    random.shuffle(TRAIN_DATA)
    losses = {}

    for text, annotations in TRAIN_DATA:
        try:
            doc = nlp.make_doc(text)
            example = Example.from_dict(doc, annotations)

            nlp.update([example], drop=0.3, losses=losses)

        except Exception as e:
            print("⚠️ Skipped bad sample:", e)
            continue

    print(f"Epoch {epoch+1} Loss:", losses)

# -------------------------
# SAVE MODEL
# -------------------------

nlp.to_disk(model_output)

print("\n✅ Model trained and saved at:", model_output)