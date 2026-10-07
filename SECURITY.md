# Security

## Reporting a vulnerability

Please report vulnerabilities in a public issue at
https://github.com/a7med7emedan/biomed-mcp-receipts/issues. Include the version, a description and,
if possible, a minimal reproduction. You will get a reply within 7 days. If you would rather not
post in public, email ahmed.hemedan@lih.lu instead.

## What the tool does on your machine

- It launches each server under test as a local subprocess over stdio, using the exact command
  pinned in `servers.yaml`. Review that file before running servers you do not trust, or use the
  Docker image, where they run as an unprivileged user.
- It sends HTTPS requests to ClinicalTrials.gov and NCBI E-utilities.
- An `NCBI_API_KEY` from the environment is sent to NCBI only. It is stripped from every URL before
  it is written to a receipt or a cassette.
- It writes only inside the output directory you give it (`runs/` by default).
