# Handoff

## Design docs

Read [docs/design/README.md](docs/design/README.md) before implementation.

## Next step

M0 setup is in progress. Commit the approved design on main, then implement the window, tray, tests, and release pipeline in the order listed in the design plan.

## Run the app and tests

M0 introduces the Python package and test suite. Planned commands from the repository root are `python -m gamehub.app` and `python -m pytest -q` using the project virtual environment.

## Project map

- `docs/design/` — requirements, flows, architecture, storage, interfaces and implementation plan.
- `docs/reviews/` — Council deliberations and verdicts.
- `docs/TESTING.md` — Windows manual acceptance checklist.
- `DECISIONS.md` — decisions and rationale.
- `LEARNING.md` — milestone learning notes.

## Known issues and blockers

- GitHub repository [game-hub](https://github.com/adhamelgohary-dev/game-hub) is verified PRIVATE. Local Git is initialized on main with origin connected.
- Windows capture and installer behavior need real-machine verification in their assigned milestones.

## Open questions for owner

- Which Windows 10/11 installations and real launchers can be used for manual acceptance? Keep automated fixtures synthetic in the meantime.
- Which local alternative data folder should be used to verify relocation? Default to the specified LocalAppData path and use a disposable temporary profile for development checks.

## Future ideas

See [extensibility](docs/design/07-extensibility.md) for the specified roadmap.
