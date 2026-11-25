# Prompt history

- **Asked:** Set up `beam_desktop`: make the folder, initialize a git repository, copy `spec.md` and `index.html` from the first app, and write an `AGENTS.md` that keeps a prompt log and commits after every request.
  **Changed:** Created `beam_desktop` and ran `git init` on branch `main`. Copied `spec.md` and `index.html` from `beam_app`, because there is no `first_app` folder and `beam_app` is the first beam app. Added `AGENTS.md` (prompt-log and commit rules, with `index.html` as the behavior reference), this `prompts.md`, and a `.gitignore` for `.DS_Store`.
  **Worked:** Yes. The copied files match the `beam_app` originals byte for byte, and the first commit holds all five files.
