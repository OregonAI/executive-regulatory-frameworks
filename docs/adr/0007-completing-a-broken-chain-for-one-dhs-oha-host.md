# Completing a broken chain for one DHS/OHA host

`sharedsystems.dhsoha.state.or.us` serves 43 of this corpus's sources — the ODHS and OHA-ISPO
policy PDFs — and serves its leaf certificate without the intermediate that links it to a
root. Browsers paper over that; `curl`, `lychee` and this corpus's fetches do not.

The consequence was not a red run. From 2026-08-05 those 43 sources had **no drift detection
at all**, and every scheduled run reported `success`: `corpus-detect-changes` runs in default
mode so an isolated failure cannot kill a 1,347-source crawl, and 43 of 1,347 is 3.2%, under
the 20% systemic guard. Nothing in the corpus changed, so nothing looked wrong. That is the
shape an **access failure** takes here, and it is why the glossary now has the word.

We decided to **supply the missing intermediate for this host**, under corpus-toolkit
[ADR 0012](https://github.com/OregonAI/corpus-toolkit/blob/main/docs/adr/0012-completing-a-chain-is-not-weakening-verification.md),
and to change nothing about the 43 documents.

The certificate lives at `_meta/tls-chain/sharedsystems.dhsoha.state.or.us.pem` — DigiCert
Global G2 TLS RSA SHA256 2020 CA1, issued by DigiCert Global Root G2, valid to 2031-03-29,
retrieved 2026-08-27 from the AIA extension of the leaf the host itself serves. The filename
is the scope: it is mounted on `https://sharedsystems.dhsoha.state.or.us` and nowhere else.

Verification is not relaxed. Measured 2026-08-27:

```
python, system store only                        CERTIFICATE_VERIFY_FAILED
python, system store + the intermediate          HTTP 200, chain verified
python, that intermediate ALONE, no root         REFUSED
```

The third line is why this is not the fourth flavour of the remedies #264 rightly rejected. A
supplement is not a trust anchor — the path still has to terminate at a self-signed
certificate the system already trusts.

## Considered options

**Doing nothing, on the grounds that the defect is Oregon's**, was this repository's position
in #264 and #140 for three weeks. It reads as rigour and is not. Refusing to fetch is not
strict verification, it is *no* verification, on sources that then go unwatched indefinitely
while a state IT ticket may or may not be answered. The upstream report is still worth
sending — it helps every automated consumer of those forms — but it is no longer what
unblocks us.

**Marking the 43 documents** — a caveat in frontmatter, or a note beside the "verify against
the official source" line — was rejected on what provenance means here. Each of the 43 carries
`source_sha256` and a committed byte-identical snapshot under `_meta/snapshots/`, so a reader
already has a complete verification path that does not depend on fetching anything. The
`source_url` is a citation to where the bytes came from, and it is correct. A caveat would
write a fact about a web server's TLS configuration into a document that reads as asserting
things about itself — the substitution `manual: true` was retired for.

**Recording the host as "known-unverifiable"**, which #140 proposed, was rejected as
vocabulary before it was rejected as design. The certificate is verifiable and we verified it.
What failed was the server's *chain delivery*. See `CONTEXT.md`, **Access failure**.

## What this does not fix

A run can still report `success` while a persistent access failure goes unremarked, for any
cause — a 403, a 404, a WAF challenge, a DNS change. `FETCH FAILED` is printed on every run
and **nothing accumulates it across runs**, so a source that has failed thirty times running
is indistinguishable from one that failed once. That is the finding #140 was really about, and
it is corpus-toolkit#166.

## A note on what the repository already knew

Both source manifests have carried the diagnosis and the remedy since they were built on
2026-07-21:

> PDFs are served from sharedsystems.dhsoha.state.or.us, which sends an incomplete TLS chain
> (missing DigiCert Global G2 TLS RSA SHA256 2020 CA1 intermediate) — ingest with
> SSL_CERT_FILE set to a bundle that supplies that intermediate (**chain completion, not
> verification bypass**).

The intermediate was named, and the distinction this ADR spends its length establishing was
already written, in the file listing the very sources that later went unwatched. #264 and
#140 were both filed and triaged as having no acceptable remedy inside the repository, by
readers who did not read the manifest note. The knowledge was not missing; it was unjoined —
which is a failure mode worth naming, because it is not fixed by knowing more.
