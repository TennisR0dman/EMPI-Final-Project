# Synthetic source extracts

These files are fabricated. They are not a hospital extract and they do not contain real patient information.

Each folder is one scenario (`baseline`, `merger`, `messy_entry`, `hard_cases`, `lab_migration`). Inside a folder:

- `registration.csv`, `lab.csv`, and `billing.csv` are the source feeds. They do not include the answer key.
- `ground_truth.csv` is the evaluation label file. The matcher does not read it. It is loaded only after scoring.

Record ids are prefixed with the scenario key so two folders can sit in one database. Regenerate everything from the repository root with `python -m empi`. Seeds and sizes are in `empi/scenarios.py`. Faker is pinned in `requirements.txt`.
