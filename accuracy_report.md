# Resume evaluation audit

**Overall accuracy: not established.**
Raw extraction is not labeled ground truth; accuracy, recall, F1 and gap correctness cannot be measured.

Reference records: 1554; predictions: 1554; matched: 1554.
Missing predictions: 0; predictions without reference: 0.

## Measured results

```json
{
  "generated_at": "2026-09-23T09:30:52.385983+00:00",
  "evaluation_mode": "SOURCE_TEXT_DIAGNOSTICS",
  "overall_accuracy_pct": null,
  "accuracy_explanation": "Raw extraction is not labeled ground truth; accuracy, recall, F1 and gap correctness cannot be measured.",
  "reference_records": 1554,
  "prediction_records": 1554,
  "resumes_evaluated": 1554,
  "missing_predictions": [],
  "predictions_without_reference": [],
  "ignored_metadata_files": [
    "batch_summary.json"
  ],
  "failed_predictions": 0,
  "prediction_status_counts": {
    "PARTIAL": 765,
    "SUCCESS": 789
  },
  "resumes_with_diagnostic_issues": 62,
  "metrics": {},
  "source_text_diagnostics": {
    "empty_source_documents": 20,
    "checked_phrases": 6459,
    "phrases_found": 6357,
    "literal_phrase_occurrence_pct": 98.42,
    "definition": "Whole normalized phrase occurs somewhere in extraction. Does NOT establish employment, correct dates/association, completeness, or accuracy."
  }
}
```

## Diagnostic examples

### a a ashwini.docx

```json
[
  {
    "type": "phrase_not_found",
    "group": "projects",
    "phrase": "project 1 microsoft role senior digital engineer duration dec 23 to dec 24 roles responsibilities"
  },
  {
    "type": "phrase_not_found",
    "group": "projects",
    "phrase": "project 2 kellogs role senior analyst in ds duration apr 23 to nov 23 roles responsibilities"
  },
  {
    "type": "phrase_not_found",
    "group": "projects",
    "phrase": "project 3 johnson brothers role senior analyst in ds duration oct 22 to mar 23"
  },
  {
    "type": "phrase_not_found",
    "group": "projects",
    "phrase": "project 4 signet role senior analyst in ds"
  },
  {
    "type": "phrase_not_found",
    "group": "projects",
    "phrase": "project 5 pepsico role software engineer"
  },
  {
    "type": "phrase_not_found",
    "group": "projects",
    "phrase": "project 6 tdc group role software engineer duration mar 20 to feb 21 roles responsibilities"
  },
  {
    "type": "phrase_not_found",
    "group": "projects",
    "phrase": "project 7 pepsico"
  }
]
```

### a a ashwini_1.docx

```json
[
  {
    "type": "phrase_not_found",
    "group": "projects",
    "phrase": "project 1 microsoft role senior digital engineer duration dec 23 to dec 24 roles responsibilities"
  },
  {
    "type": "phrase_not_found",
    "group": "projects",
    "phrase": "project 2 kellogs role senior analyst in ds duration apr 23 to nov 23 roles responsibilities"
  },
  {
    "type": "phrase_not_found",
    "group": "projects",
    "phrase": "project 3 johnson brothers role senior analyst in ds duration oct 22 to mar 23"
  },
  {
    "type": "phrase_not_found",
    "group": "projects",
    "phrase": "project 4 signet role senior analyst in ds"
  },
  {
    "type": "phrase_not_found",
    "group": "projects",
    "phrase": "project 5 pepsico role software engineer"
  },
  {
    "type": "phrase_not_found",
    "group": "projects",
    "phrase": "project 6 tdc group role software engineer duration mar 20 to feb 21 roles responsibilities"
  },
  {
    "type": "phrase_not_found",
    "group": "projects",
    "phrase": "project 7 pepsico"
  }
]
```

### abhaykumartiwari.docx

```json
[
  {
    "type": "phrase_not_found",
    "group": "projects",
    "phrase": "project"
  },
  {
    "type": "phrase_not_found",
    "group": "projects",
    "phrase": "project"
  },
  {
    "type": "phrase_not_found",
    "group": "projects",
    "phrase": "project"
  },
  {
    "type": "phrase_not_found",
    "group": "projects",
    "phrase": "project"
  },
  {
    "type": "phrase_not_found",
    "group": "projects",
    "phrase": "project"
  }
]
```

### abhishek.s.pdf

```json
[
  {
    "type": "phrase_not_found",
    "group": "work_experience",
    "phrase": "turn turtle private limited g square"
  }
]
```

### aditya_sharma.pdf

```json
[
  {
    "type": "empty_source_text",
    "note": "Cannot verify predictions against an empty reference; excluded from phrase occurrence denominator."
  }
]
```

### amrikabhattacharjee.pdf

```json
[
  {
    "type": "phrase_not_found",
    "group": "projects",
    "phrase": "project 1 adelaide bank"
  },
  {
    "type": "phrase_not_found",
    "group": "projects",
    "phrase": "project 2 merkur privatbank"
  },
  {
    "type": "phrase_not_found",
    "group": "projects",
    "phrase": "project 3 barrenjoey capital"
  }
]
```

### anirudha_kaple.docx

```json
[
  {
    "type": "empty_source_text",
    "note": "Cannot verify predictions against an empty reference; excluded from phrase occurrence denominator."
  }
]
```

### anshthakur.docx

```json
[
  {
    "type": "phrase_not_found",
    "group": "projects",
    "phrase": "project"
  },
  {
    "type": "phrase_not_found",
    "group": "projects",
    "phrase": "project"
  }
]
```

### anshthakur_1.docx

```json
[
  {
    "type": "phrase_not_found",
    "group": "projects",
    "phrase": "project"
  },
  {
    "type": "phrase_not_found",
    "group": "projects",
    "phrase": "project"
  }
]
```

### aruneshpandey.docx

```json
[
  {
    "type": "empty_source_text",
    "note": "Cannot verify predictions against an empty reference; excluded from phrase occurrence denominator."
  }
]
```
