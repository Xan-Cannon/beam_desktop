# Agent instructions

## After every request
1. Add an entry to the end of `prompts.md` with three lines:
   - **Asked:** what I asked for, in one or two sentences.
   - **Changed:** which files you changed and what you did to them. If you changed no files, say so.
   - **Worked:** Yes, No, or Partly, and how you checked.
2. Commit all changes, including the `prompts.md` entry, with a short message
   that describes the request. Make one commit per request. Do not push unless
   I ask you to.

## Reference files
- `spec.md`: the requirements for the app.
- `index.html`: the working web version of the Beam Designer from `beam_app`.
  Use it as the reference for how the app should behave: inputs, calculations,
  checks, diagrams, and validation results. The desktop app should match its
  results. Do not edit `index.html` unless I ask you to.
