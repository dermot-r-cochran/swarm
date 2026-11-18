# Contributing to swarm (EPISTEME)

Contributions are welcome: bug reports, fixes, tests, documentation and focused improvements.

## Before you start

- For anything beyond a small fix, open an issue first describing the problem and the change you have in mind, so the approach can be agreed before you spend time on it.
- Read `AGENTS.md` first. Its principles are binding here: never invent facts, APIs or results; keep FACT, THEORY, OPINION and FICTION separate; fail loudly rather than return a plausible placeholder.
- The five accepted decisions in `docs/adr/` each have a guard test. A change that needs one undone is proposed as a new ADR, not made by editing the old one or its guard.

## Making a change

- Keep a pull request to one change, and say in its description what it changes and why.
- Run what CI runs before you push:

```bash
python -m pip install -e ".[dev]"
pytest --cov=episteme --cov-fail-under=100
ruff check .
mypy
python .github/scripts/check_docs.py
```

- Every capability the README claims names the test that proves it, or says *no test yet* or *not yet implemented*. A new capability lands with its tests and its README row in the same pull request, and a renamed test updates the rows that cite it.
- The coverage threshold (100%) is a ratchet: it may rise with tests that earn it, never fall.
- A `noqa` or `type: ignore` carries a written reason beside it, and the suite stays warning-free.

## How a pull request is reviewed

The repository has one maintainer, Dermot Cochran, so a pull request may wait a while before anyone looks at it.

- CI must be green. A failing check is the first thing to fix.
- The review may be assisted by an AI tool, which reads the change and reports to the maintainer. It does not approve or merge anything.
- **Every outside pull request is merged by the maintainer, never by an automated process or an AI tool,** however small.
- A pull request may be declined, or asked to change shape, when it moves the project somewhere it is not meant to go. That is not a judgement on the work.

## Licence

Contributions are accepted under this repository's licence, the Eclipse Public License 2.0 (`LICENSE`), the same terms everyone else receives the code under. No sign-off line and no contributor licence agreement are required. Only contribute work you have the right to license on these terms.

## Security

Please don't describe a security problem in a public issue. Open an issue saying only that you have one, and a private way to send the details will be arranged.
