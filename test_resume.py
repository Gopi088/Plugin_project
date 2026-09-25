import json
import sys
from scripts.resume_parser import parse_resume

def main():
    if len(sys.argv) < 2:
        print("Usage: python test_resume.py <resume_path>")
        exit()

    file_path = sys.argv[1]

    profile = parse_resume(file_path)

    print("\n====== Parsed Resume ======\n")
    print("Here is the extracted structured resume data in JSON format:\n")

    print(json.dumps(profile, indent=2))

    # ✅ SAVE OUTPUT (ADD THIS)
    with open("output.json", "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2)

    print("\n✅ Output saved to output.json")

if __name__ == "__main__":
    main()
