import json

# load files
with open("dataset/ground_truth.json") as f:
    gt = json.load(f)

with open("output.json") as f:
    pred = json.load(f)


# -------------------------
# BASIC FIELDS
# -------------------------

def check(field):
    if gt[field] == pred[field]:
        print(f"✅ {field} correct")
    else:
        print(f"❌ {field} mismatch")
        print("GT :", gt[field])
        print("PR :", pred[field])


check("name")
check("email")
check("phone")


# -------------------------
# SKILLS EVALUATION
# -------------------------

gt_skills = set([s.lower() for s in gt["skills"]])
pred_skills = set([s.lower() for s in pred["skills"]])

common = gt_skills & pred_skills

precision = len(common) / len(pred_skills) if pred_skills else 0
recall = len(common) / len(gt_skills) if gt_skills else 0

print("\n🎯 SKILLS")
print("Matched:", len(common))
print("Precision:", round(precision, 2))
print("Recall:", round(recall, 2))


# -------------------------
# EXPERIENCE CHECK
# -------------------------

print("\n💼 EXPERIENCE CHECK")

for i, gt_exp in enumerate(gt["experience"]):

    if i >= len(pred["experience"]):
        print(f"❌ Missing experience {i}")
        continue

    pred_exp = pred["experience"][i]

    if gt_exp["role"].lower() in pred_exp["role"].lower():
        print(f"✅ Role {i} correct")
    else:
        print(f"❌ Role {i} mismatch")

    if gt_exp["company"].lower() in pred_exp["company"].lower():
        print(f"✅ Company {i} correct")
    else:
        print(f"❌ Company {i} mismatch")


# -------------------------
# PROJECTS CHECK
# -------------------------

print("\n🚀 PROJECTS CHECK")

for i, gt_proj in enumerate(gt["projects"]):

    if i >= len(pred["projects"]):
        print(f"❌ Missing project {i}")
        continue

    pred_proj = pred["projects"][i]

    if gt_proj["name"].lower() in pred_proj["name"].lower():
        print(f"✅ Project {i} correct")
    else:
        print(f"❌ Project {i} mismatch")


print("\n🏁 DONE")