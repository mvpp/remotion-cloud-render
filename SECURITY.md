# Security

This repo holds no secrets. The scripts use your local `gcloud` login. Deployment coordinates live in
`~/.config/remotion-cloud-render/config.env` on your machine; never commit that file.

- The render bucket is private (uniform access, public access prevention) and deletes every file after 7 days.
- Render tasks run as a dedicated service account (`remotion-render@<project>`) that can read and write that
  bucket only. It has no other project role.
- The Cloud Run Job has no public endpoint; only identities with `run.jobs.run` on the project can start it.
- Spend guards: `MAX_PARALLEL` (tasks at once), `TASK_TIMEOUT` (one hour by default) and `MAX_RETRIES`. Spend
  beyond your monthly credit is charged to the billing account's payment method, so set a budget alert if you
  want an email warning (budgets only notify; they never stop anything).

Report security problems as a GitHub issue without your project id, billing account or any key.
