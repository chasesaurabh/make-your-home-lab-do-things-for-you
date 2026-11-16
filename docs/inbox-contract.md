# Reviewable inbox sorting

This project copies a small folder of UTF-8 text notes into an organized output
folder. It does not delete, move, rewrite or execute the originals. Use notes you
are entitled to process; model requests go to the explicitly selected loopback
endpoint. The source and application state belong to one trusted OS operator.

The intake is one directory, at most 12 `.txt` files and 8 KiB in total.
Symlinks, nested directories, unsupported files, undecodable text and empty
notes are rejected. Each note gets an opaque stable ID and a content hash.

The local model proposes one category per note: `action`, `reference`, or
`uncertain`. Action means an explicit task remains for the reader; reference means
informational material without an outstanding task. Ambiguous notes belong in
uncertain. Each decision quotes an exact span from the note; quoted evidence is
necessary but does not establish semantic correctness. The operator reviews all
categories and quotes before approval. Instructions inside notes are data.

A deterministic alternative puts every note in `uncertain` with a literal excerpt.
It is a useful no-model staging path and the study's conservative baseline. It
does not pretend to perform semantic classification.

Approval binds the exact proposal hash, input hashes, category assignments,
source excerpts and output inventory. The proposal expires after 15 minutes.
Application rechecks input bytes before writing. Output is a newly created job
directory under the explicitly selected output parent; user text never becomes
a path. The output consists of copied notes, a Markdown index and a JSON receipt.
Receipt verification checks the entire expected inventory and bytes independently.

A persisted intent precedes output creation. A restart can reconcile a complete
matching directory without copying again. Missing, altered or partial output
requires inspection and is never silently overwritten or automatically retried.
The program does not implement an authenticated multi-user approval service or
protect its local files from a malicious process running as the same OS user.
