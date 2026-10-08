# Contributing

This is an experimental research workflow. Reports about unnecessary complexity
or an approach that works better with fewer rules are welcome.

## Issues

Describe what you tried, what happened, and what you expected. For a bug, include
your OS, Python version and a small reproducible example. Use synthetic examples
instead of private research, credentials or unpublished drafts.

For a feature proposal, explain the research problem it would help with and how
we could tell whether it works. An open issue is a discussion, not a promise that
the feature will be built.

## Pull requests

Keep changes focused. Explain the problem, the resulting behavior and the checks
you ran. Ask first in an issue before a large redesign. Documentation and simpler
defaults are useful contributions too.

Run `make validate` for profile changes. For lab-code changes, create a disposable
lab with the affected modules and run its doctor, validation and relevant tests.
Do not use a live research project as a test fixture. `make verify` will report
your edited package files as changed; that is expected during development.

Keep research results and personal preferences outside the shared factory.
Contributions to this repository are provided under its MIT License.

## AI contributions

Be clear about the tools used to prepare a change. For changes prepared with
Codex, the maintainer uses their own Git identity and adds
`Co-authored-by: Codex <codex@openai.com>` to the commit message. Add this credit
only when Codex contributed to that change; purely human changes do not need it.
