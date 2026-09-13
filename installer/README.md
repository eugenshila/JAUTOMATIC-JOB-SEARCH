# Windows installer placeholder

The installer is intentionally deferred until Phase 12. The planned build is:

1. Build and test the PyInstaller executable.
2. Package it with Inno Setup or WiX.
3. Create shortcuts and the uninstall entry.
4. Create the local data directory without overwriting a user's Master CV.
5. Register Windows Task Scheduler only when the user explicitly opts in.
6. Sign release artifacts before distribution.

No installer script is included in Phase 1 because packaging a partially implemented application would make the startup and update behavior misleading.
