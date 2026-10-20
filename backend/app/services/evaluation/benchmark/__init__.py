"""Overnight business-evaluation benchmark: versioned, synthetic, reproducible.

This package does **not** replace the existing ``rag_evaluator`` / ``ai_skills.evaluation``
platform.  It is a thin, read-only harness that reuses those services through their real
entry points so a change can be compared against a frozen dataset:

* :mod:`app.services.evaluation.benchmark.dataset` - case schema, content hashing and the
  frozen dev/holdout split;
* :mod:`app.services.evaluation.benchmark.cases` - the synthetic case corpus;
* :mod:`app.services.evaluation.benchmark.runner` - per-case execution against the real
  ``grounded_answer`` / ``recall_fields`` service chain, with only the model boundary
  replaced (never the surrounding logic).

Every case here is explicitly synthetic.  No row is copied from a business database and
no metric produced by this harness may be described as business-expert accuracy.
"""
