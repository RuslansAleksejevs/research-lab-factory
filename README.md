# Research Lab Factory

## What this does

The factory creates a separate workspace (a folder) in Codex for your research project. The laboratory keeps sources, attempts, results and next steps so you can continue the work in later chats. Describe your task, and Codex sets up the laboratory for you.

## Download and start

[**Download ZIP**](https://github.com/RuslansAleksejevs/research-lab-factory/releases/download/v0.1.0-alpha.1/research-lab-factory-v0.1.0-alpha.1.zip), unzip it and open the extracted folder as a project in Codex. Describe your task and ask: **"Create a research laboratory for this task."** Open the new laboratory folder created next to the factory as a separate Codex project, and work there.

**Using GitHub's buttons:** on this repository's main page, click **Code** above the file list, then **Download ZIP**. This downloads the current repository; the direct link above downloads the fixed release.


This is the first experimental release, **v0.1.0-alpha.1**. Try it, inspect what helps, and report
what gets in the way. Tests check software behavior and record consistency; they
do not establish mathematical correctness, novelty or research effectiveness.
The author's work on this workflow began in early July 2026. Future releases and
refactoring are expected. Licensed under the [MIT License](LICENSE).

[Download this release](https://github.com/RuslansAleksejevs/research-lab-factory/releases/tag/v0.1.0-alpha.1) · [Release notes](RELEASE_NOTES.md) · [Features and options](#what-is-included) · [Issues and feedback](https://github.com/RuslansAleksejevs/research-lab-factory/issues)

Codex prepared this entire repository. I just asked it, from my local lab-factory project in Codex, to put together a GitHub template I could send to Ilya.

This factory is **one proposed implementation of a research workflow**. I have no evidence that it works better than other systems, or even that it works better than out-of-the-box Codex starting in a completely empty folder with no preset structure. I care a lot about robustness, even if the amount of scaffolding here might suggest otherwise: the workflow should tolerate variation, preserve useful work, and avoid narrowing how research can be done. The structure itself still has to earn its keep.

See [related projects and alternative workflows](COMPARISON.md) for a survey of 63 entries, ordered by relevance, with evidence and limitations.

## Quick start

The tested setup is **macOS, Python 3.9 or 3.14, and Codex**. Unpack the ZIP into an ordinary folder. New laboratories are created next to it, so use a location where you can create folders.

1. Open the factory folder as a Codex project.
2. Describe your research question and attach any draft, notes or sources.
3. Ask: "Create a research laboratory for this project."
4. Open the new laboratory folder as its own Codex project and work there.

The factory creates and checks the workspace. It does not start research,
install Lean, call Claude, create a GitHub repository or publish your work.
You can use the laboratory without any optional integration.

For a technical smoke test, run these commands **from the factory folder**.
They create a new sibling folder using a synthetic example:

```sh
python3 -B scripts/check_public_kit.py validate
python3 -B scripts/new_lab.py plan --request profiles/examples/minimal_article.json
python3 -B scripts/new_lab.py create --request profiles/examples/minimal_article.json
```

For your own project, ask Codex to adapt a starter profile and choose a new
folder name. Existing laboratories are never overwritten. Private local add-ons
(`bootstrap.local_layer`) are not included; the starter profiles do not need them.

## What is included

"Included" does not mean "running". Some features are part of every lab, some
are selected when creating it, and some have an explicit on/off switch.

| Feature | Availability and default | Current limits |
|---|---|---|
| A separate workspace for each research project | Core factory function | Creation and first-run checks are tested; existing labs are not automatically upgraded. |
| Saved results, failed attempts and next steps | Built into mathematical labs | Recovery is tested; lost original evidence cannot be reconstructed from a hash. |
| Source notes, proof attempts and critical reviews | Built into mathematical labs; used when requested | These are AI workflows, not guarantees of correct proofs or independent judgment. |
| Paper writing and computational work | Modules selected at creation; both are in the math starter profiles | Templates and roles do not install a complete computational environment. |
| Claude Code | Included, **off by default**; enabled in the lab's integration settings | Tested direction is Codex → Claude on macOS. Requires an installed, authenticated Claude Code. |
| Lean Room | Select the `formalization` module; it starts **disabled** | Requires a pinned Lean setup and explicit activation. Has implementation and real tests; not automatic formalization of arbitrary mathematics. |
| Longer research campaigns, discovery portfolios, collaboration and talks | Additional modules selected for a suitable project | Advanced workflows; not needed for the starter and not all field-tested as public features. |
| Control Room dashboard and fleet upgrades | **Not included in this release** | These remain separate private development tools. |

## Cross-checking and verification

The proof workflow distinguishes four levels of reviewer independence:

- **I0 — Self-check:** the author checks their own work; this cannot certify it.
- **I1 — Involved reviewer:** helped develop or critique the approach; can advise but cannot give the decisive audit.
- **I2 — Separate reviewer:** did not write the proof but has seen earlier drafts or the favored approach; useful as a second check.
- **I3 — Blind reviewer:** checks the exact claim and completed candidate proof without the author's surrounding discussion or intended repairs. At least one such audit is required before closing a proof.

These are independence levels, not four mandatory rounds. Imported results also
need source checks; high-risk claims should receive two audits using different
checking strategies. Optional formal verification needs a separate check that
the formal statement matches the intended claim. AI agreement alone is not proof.

## Known limitations

- General Linux, Windows and Claude as the leading agent have not been verified.
- More rules and accumulated context may narrow research. No comparison has
  established that this factory outperforms a simpler setup.
- The optional Claude adapter can preserve a written report even when process
  cleanup fails to record completion. Check the report and actual process state;
  do not treat a stale "running" label as proof that Claude is still working.
- Some memory diagnostics need a separate recovery search to identify a damaged
  record. A later correction that depends on missing evidence may remain blocked
  until the exact evidence is restored; unrelated work can continue.

## Useful research memory

Before repeating an investigation, search the laboratory's existing checkpoints
and linked results. After substantial work, keep one compact checkpoint of the
question, outcome, evidence, uncertainty, unsuccessful approaches and next step.
A fresh chat should read that record before spending more compute on the same
question. Generated records start with honest unverified/unknown status; an AI
answer or a hash is not proof.

## Optional Claude

Claude Code integration is off by default. Enable it only for work you request;
Codex handles the terminal workflow and preserves the selected session's output.
Public web access also starts off in the round template. Enable `public_web`
only for a round whose requested scope includes public research reading.
The optional adapter currently uses a macOS neutral packet directory and expects
a locally installed, authenticated Claude Code CLI. Its local documentation
explains preparation, bounded execution, pause/resume and result intake.
No generation command starts Claude, uses a network, initializes Git or publishes
anything. Claude as the primary agent, native Windows, and general Linux support
have not been verified for this release.

## Check your copy

`make validate` checks the example profiles. `make verify` detects changes to
packaged files. Your generated lab has its own checks. These checks do not prove
mathematical truth or research quality. The package excludes private project
memory, personal preferences and existing research laboratories.

## Feedback and contributions

Please report confusing steps, failures and unnecessary restrictions. See
[CONTRIBUTING.md](CONTRIBUTING.md) for a short guide to issues and pull requests.

## Why I am sharing this — and what worries me

I often wonder whether the rules and accumulated context in this factory constrain research as much as they help it. They may steer a model toward familiar approaches, reinforce early assumptions, or keep solving limitations that newer models have already outgrown. [This post by the amazing DHH](https://x.com/dhh/status/2107823432205484040) captures a concern I take seriously: capable models may need much less scaffolding than we are tempted to build around them. I want this system to become more robust over time: able to support good research without making it depend on brittle rules or unnecessarily narrowing how it can be done.

The version I am sharing grows out of a workflow I have used for several months. Its core has stayed roughly the same since early July 2026, with many improvements along the way. I am putting it here for two reasons:

1. **To preserve a chronicle of my research workflow.** Changes in this repository, with releases as milestones, should make it possible to see how the workflow evolves over the coming months and years. I expect substantial changes. I will probably eventually abandon this setup for a specialized tool built by a frontier lab, informed by the experience of many researchers like me. If that happens, I will turn this repository into a museum. I think the history is worth preserving.

2. **A couple of people asked me to share the factory.** I am happy to do so, but please use it at your own risk. This is an experimental snapshot of something I use, with no demonstrated advantage over a simpler setup. What especially excites me about sharing it is hearing independent opinions on whether the architecture helps research or gets in its way.
