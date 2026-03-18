import spacy
import random
from spacy.training import Example
from dataset.train_data import TRAIN_DATA

nlp = spacy.blank("en")
ner = nlp.add_pipe("ner")

# add labels
for _, annotations in TRAIN_DATA:
    for ent in annotations["entities"]:
        ner.add_label(ent[2])

optimizer = nlp.begin_training()

# 🔥 TRAINING LOOP IMPROVED
for epoch in range(50):

    random.shuffle(TRAIN_DATA)
    losses = {}

    for text, annotations in TRAIN_DATA:

        doc = nlp.make_doc(text)
        example = Example.from_dict(doc, annotations)

        nlp.update(
            [example],
            drop=0.3,
            losses=losses
        )

    print(f"Epoch {epoch} Losses {losses}")

# save model
nlp.to_disk("model")

print("✅ Model trained and saved!")