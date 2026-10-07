# Changelog

## 0.1.0, 2026-10-07

First release.

- Seven scored dimensions: conformance, schema, correctness, freshness, attribution, robustness, stability.
- Two capabilities: `trial.lookup` against the ClinicalTrials.gov v2 API, and `literature.search`
  against NCBI E-utilities.
- Adapters for BioMCP 0.9.1, pubmed-mcp-server 2.10.20 and clinicaltrialsgov-mcp-server 2.9.11,
  each checked in CI against the server's own tool schemas.
- Oracles in live, record and replay modes, with cassettes for offline reruns.
- Hash-chained receipts, `bmr verify`, and an RO-Crate (Process Run Crate profile) per run.
- A planted-fault server with seven faults; CI requires each to trip its own dimension and no other.
- One fresh MCP session per check, so a hung or crashed call cannot affect the next check.
- Upstream outages are reported and left unscored instead of counted as passes.
- Docker image with every pinned server; CI on Python 3.11 to 3.13; weekly live run.
