"""
Shared data contracts mirrored from the architect's ADRs.

These are the harness's own copies of the shapes defined in docs/adr/0001,
0002, 0004, 0005 — not production code. They exist so the eval harness can be
written and validated *before* backend/agent-engineer code lands. Once real
implementations exist, `harness/pipeline_adapter.py` and
`harness/retriever_adapter.py` are the seam that maps between them.

If an ADR changes, update the corresponding contract here first — the harness
is built against the ADRs, not against whatever backend happens to ship.
"""
