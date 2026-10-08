# v0.1.0-alpha.1 — first experimental release

Released 8 October 2026 under the [MIT License](LICENSE).

Research Lab Factory creates a separate, durable workspace for each substantive
research project. It packages a workflow used and revised since early July 2026.
Please try it and tell us which parts help, fail, or impose unnecessary rules.

## Start here

Download the source ZIP from the
[release page](https://github.com/RuslansAleksejevs/research-lab-factory/releases/tag/v0.1.0-alpha.1),
unpack it, and open that folder as a Codex project. Describe your question and
ask Codex to create a research laboratory. Open the generated laboratory as its
own project to do the research. See the [quick start](README.md#quick-start).

## Included

- A standalone factory, neutral starter profiles, and checked lab creation.
- Durable records of results, uncertainty, failed routes, evidence and next steps.
- Source checking, proof attempts and separate critical reviews.
- Optional paper, computation, collaboration and other research modules.
- Optional Claude Code integration and Lean Room, both off by default.
- A [feature overview](README.md#what-is-included) and
  [63 related projects](COMPARISON.md), with evidence and limitations.

The private Control Room, fleet upgrades, personal research materials and
private Git history are not part of this release.

## Checks and limits

The tested setup is macOS with Python 3.9 and 3.14, using Codex as the leading
agent. Release checks cover packaging, a clean file-only checkout, generated-lab
validation and recovery of a synthetic research checkpoint in a fresh process.
They do not prove mathematical correctness or research effectiveness. Linux,
Windows and Claude as the leading agent remain unverified.

There is no evidence that this workflow beats other systems or plain Codex in an
empty folder. Optional Claude process-status reporting and some memory recovery
diagnostics still have limits; see [known limitations](README.md#known-limitations).
Future releases may substantially refactor the workflow or introduce incompatible
changes. Existing laboratories remain independent snapshots.

The public release numbering starts here. `TEMPLATE_VERSION` records the
underlying kernel's earlier development version; it is a separate provenance
marker, not the public release number.

Codex prepared this repository under Ruslan's direction. Codex-assisted release
commits include a `Co-authored-by` credit. Feedback, simpler alternatives and
focused pull requests are welcome; see [contributing](CONTRIBUTING.md).
