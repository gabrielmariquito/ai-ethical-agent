# Ontology provenance

## relaieo.ttl — upstream, vendored verbatim

- **Ontology:** Relational AI Ethics Ontology (RelAIEO)
- **Authors:** Cheshta Arora, Debarun Sarkar
- **Source:** https://ontology.audit4sg.org/ (part of the Audit4SG project)
- **Downloaded from:** https://ontology.audit4sg.org/ontology.ttl
- **License:** GNU General Public License v3 (as declared in the ontology header)
- **Namespace:** `http://www.ontology.audit4sg.org/RelAIEO#`

RelAIEO is a proof-of-concept, **relational and reflective** auditing ontology.
It models actors, domains, AI systems, ethical frameworks, identified harm
risks, ethical parameters and ethics-manipulation patterns, and it attaches a
`rdfs:provocation` (a reflective question) and `rdfs:references` (scholarly
quotes) to most concepts. It adopts an open-world assumption and is explicitly
a partial, non-exhaustive view — it is designed to help humans *explore and
audit* the ethics of an AI system, **not** to make automated allow/deny
decisions.

This file is vendored **unmodified**. Do not edit it; re-download from the
source to update. Two external classes it imports
(`aexp:expectation`, `ateo:ethical_assessment`) live in other namespaces and
are intentionally not loaded as RelAIEO concepts.

## relaieo_grounding.json + relaieo_norms.json — our layers

Because RelAIEO has **no lexicalizations** (no surface terms) and **no deontic
norms** (no effects), two thin layers that we maintain sit on top of it and
reference its concept IDs:

- `relaieo_grounding.json` — maps en/pt-BR surface text to a subset of RelAIEO
  concept IDs, so the guardrail can activate concepts from a prompt/response.
- `relaieo_norms.json` — verification norms (RQ3) that fire on combinations of
  activated concepts. Faithful to RelAIEO's reflective nature, an activated
  harm risk combined with a build/deploy intent is **ESCALATED** for human
  review and the concept's RelAIEO provocation is surfaced as the review
  prompt. Hard blocks remain in `policies/core_policy.json` (layer #1).

Keeping these separate means the professor's ontology stays authoritative and
re-syncable, while our text-grounding and enforcement decisions evolve
independently.
