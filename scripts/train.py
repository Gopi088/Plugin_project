import spacy
import json
import random
import os
from spacy.training.example import Example

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

annotations_path = os.path.join(BASE_DIR, "dataset", "annotations.json")
model_path = os.path.join(BASE_DIR, "model")

with open(annotations_path, "r", encoding="utf-8") as f:
    data = json.load(f)

TRAIN_DATA = []

for item in data:

    text = item["text"]
    entities = item["entities"]

    # remove overlapping entities
    entities = sorted(entities, key=lambda x: x[0])
    clean_entities = []

    last_end = -1

    for start, end, label in entities:

        if start >= last_end:
            clean_entities.append((start, end, label))
            last_end = end

    TRAIN_DATA.append((text, {"entities": clean_entities}))

nlp = spacy.blank("en")
ner = nlp.add_pipe("ner")

labels = ["EMAIL", "PHONE", "SKILL"]

for label in labels:
    ner.add_label(label)

optimizer = nlp.begin_training()

for epoch in range(40):

    random.shuffle(TRAIN_DATA)
    losses = {}

    for text, annotations in TRAIN_DATA:

        try:
            doc = nlp.make_doc(text)
            example = Example.from_dict(doc, annotations)

            nlp.update([example], drop=0.2, losses=losses)

        except:
            continue

    print("Epoch:", epoch, "Loss:", losses)

nlp.to_disk(model_path)

print("\n✅ Model training complete")