# Import Records

Successful import provenance is appended under `import_receipts/` in the newly
published candidate.  The new receipt is exclusive.  Import semantically
replays the staged candidate and compares its derived status with the manifest
before atomic publication; a rejected package leaves no destination candidate.
