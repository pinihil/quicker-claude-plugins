# Evals

`evals.json` holds the prompts and expectations used to measure the skill (with vs without it)
when it changes. The input .docx files are **not** in this public repository - keep them in Quicker's
private storage and copy them into a local folder that git ignores (`evals/inputs/`) before running the
evals with the skill-creator workflow.

`tests/smoke_test.sh` is the public, fictional end-to-end check that runs in CI on every change.
