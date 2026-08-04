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
  activated concepts. An activated harm risk combined with a build/deploy
  intent is **DENIED**, and the concept's RelAIEO provocation is surfaced in
  the refusal message. Hard blocks otherwise remain in
  `policies/core_policy.json` (layer #1).

  **Deliberate departure from RelAIEO's own stance:** RelAIEO was designed
  for reflective *human* auditing, not automated allow/deny decisions (see
  above). An earlier version of this norms layer honored that by using an
  `ESCALATE` effect (withhold + route to human review) instead of a hard
  block. That effect was removed from the system in favor of a simpler
  ALLOW/FLAG/REWRITE/DENY lattice, so these norms now act unilaterally
  (`DENY`) instead of deferring to a human reviewer. This is documented here
  as an explicit, known trade-off, not as fidelity to RelAIEO's reflective
  philosophy — the `rdfs:provocation` still reaches the end user, but as
  refusal text, not as a review prompt for an auditor.

Keeping these separate means the professor's ontology stays authoritative and
re-syncable, while our text-grounding and enforcement decisions evolve
independently.

## harm_taxonomy.ttl + harm_grounding.json + harm_norms.json — **ours, not upstream**

Added 2026-08-04. These three files are **authored here**. Neither RelAIEO's
authors nor its GPL v3 licence apply to them; the loader keeps their metadata
separate from RelAIEO's for exactly that reason (`relaieo._METADATA_DANO`), and
every concept carries the source it came from (`Concept.source`, `"relaieo"` or
`"harm"`).

**Why the taxonomy did not fit RelAIEO's vocabulary.** Measured, not assumed:
of RelAIEO's 154 classes, **none** names violence, weapons, theft, drugs,
self-harm, sexual content, extremism or intrusion. The complete list of its
harm-bearing concepts is `bias`, `censorship`, `defamation`, `deskilling`,
`dishonest_anthropomorphism`, `exclusionary_norm`, `hate_speech`, `inaccuracy`,
`inequality`, `information_disorder`, `surveillance`, `threat_to_privacy`,
`weakening_of_democracy`, plus the `ethics_manipulation` family and three
umbrellas. Over the `tune` half of the external benchmarks, **106 of 198 DENY
cases fall in a category RelAIEO does not name**.

**This is not a gap in RelAIEO.** It is a gap of fit between RelAIEO and this
task. RelAIEO is a reflective instrument for auditing *systems being designed*;
these benchmarks are *content* produced by an assistant. The two are different
objects, and the honest response is a second vocabulary beside the first, not a
stretched reading of the first.

**How the two connect without touching the vendored file.** Where one of our
concepts specialises a RelAIEO one, its `rdfs:subClassOf` names the RelAIEO id
directly — `:targeted_surveillance rdfs:subClassOf :surveillance`. Relation
endpoints are validated against the **union** of both sources, so the link
resolves and activation propagates into RelAIEO's hierarchy with **zero edits**
to `relaieo.ttl`. Five of our twelve concepts have a RelAIEO parent; seven do
not, and that proportion is what sizes the gap.

**Why our norms drop `design`.** Five of RelAIEO's six norms require the
`design` concept — an intent to *build* a system. An assistant answer that
explains how to follow someone mentions building nothing, so those norms never
fired on it: that is the measured cause of a 0.0615 recall on BeaverTails.
Our norms act on **content** and therefore do not require `design`. The six
RelAIEO norms are untouched, `design` and all.

`harm_taxonomy.ttl` declares **no version**, like `relaieo.ttl`: the format does
not carry one. For both, the sha256 in `configuration.artifacts[]` is the only
identity they have.
