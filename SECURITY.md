# Security and blinding

RRG packages may contain sensitive research data. The CLI operates only on local
paths and binds its GUI to `127.0.0.1`. It does not upload data or invoke models.

The linter is a defense-in-depth gate, not a semantic confidentiality guarantee.
Operators must review flagged result tokens and the final package manifest before
sharing. Never use `--force` without recording why the hard failure is safe.

Report a suspected routing or blinding bypass privately to the repository owner;
do not include real datasets or answer keys in a public report.
