# Learning guide

## D — Design

A requirement describes what someone can verify. A module boundary says who owns the work and what information crosses that boundary. A database transaction updates related rows together, while staged media writes let the app recover when Windows closes it between a file move and a DB update.

Read in this order:

1. [Design summary](docs/design/README.md)
2. [Requirements](docs/design/01-requirements.md)
3. [Architecture](docs/design/03-architecture.md)
4. [Data model](docs/design/04-data-model.md)
5. [Interfaces](docs/design/05-interfaces.md)

Try it yourself. Trace what happens when a game closes while a voice note is still recording. Identify who owns the session ID and what should happen if the note cannot be written.
