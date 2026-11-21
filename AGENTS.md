# Game Hub working rules

- Follow PROMPT.md and STRUCTURE.txt. On resume, pull the verified private remote without rewriting history, then read HANDOFF.md, PROGRESS.md, DECISIONS.md and the design index. Run the full existing test suite and build first. Follow the exact next step.
- Route work to the build roles in the design plan. Design comes before implementation. Update the relevant design file and DECISIONS.md before changing the design in code.
- Use the four Review Council roles on the overall plan and at each milestone gate. Record the Judge's verdict in docs/reviews and address required changes within two re-review rounds.
- Keep progress and handoff current after each task. Write a Tutor entry per milestone. Mark tasks simple or complex. Preserve green main and record unfinished implementation on a wip branch when needed.
- Check tests and the staged diff before small commits. Confirm the intended GitHub repository is private before pushing, verify visibility after changes, and never force-push. Release only milestone tags through the Windows build.
- Keep v1 offline and user data out of Git. Use Windows Graphics Capture for the exact foreground game window. The app has no injection, game hooks, or memory reads. Keep code and technical docs in English and the UI accessible in English and Arabic.
