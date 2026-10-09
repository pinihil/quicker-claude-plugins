# Evals

`evals.json` holds the prompts and expectations used to measure the skill (with vs without it)
when it changes. The input .docx files are **not** in this public repository - keep them in Quicker's
private storage and copy them into a local folder that git ignores (`evals/inputs/`) before running the
evals with the skill-creator workflow.

`form-evals.json` is the same for **quicker-appraisal-form**. Its inputs: an office form exported with
`get_form_template` (`form.json`), the connector's tool descriptions (`connector_tools.md`), and for the
hand-off eval a bank report and the template skill's `plan.json`. The runs call
`plan_form_template_changes`: either against a test organization in Quicker, or a local simulator built
from Quicker's server code - which stays out of this public repository like the inputs. Apply is off in
these evals (Quicker's default), so a run ends at the approval question.

`tests/smoke_test.sh` is the public, fictional end-to-end check that runs in CI on every change.
