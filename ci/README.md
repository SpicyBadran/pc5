# CI pipeline (not yet active)

`ci/build.yml` is the PC5 build-and-release pipeline. It is **stored here rather
than in `.github/workflows/` on purpose**: the GitHub App that authored this
branch has repository admin rights but not the *workflows* permission, so GitHub
rejects any push or API call that creates a file under `.github/workflows/`
(`refusing to allow a GitHub App to create or update workflow ... without
workflows permission`).

Nothing about the pipeline is missing — only the location. To activate it:

```sh
# 1. from a checkout of main with this file present
git mv ci/build.yml .github/workflows/build.yml
git commit -m "ci: activate the build and release pipeline"
git push

# 2. (or grant the GitHub App the "Workflows" permission and let an agent do it)
```

Then cut a release:

```sh
git tag -a v0.2.0 -m "PC5 0.2.0"
git push origin v0.2.0
gh run watch
gh release view v0.2.0 --json assets
```

## What the pipeline does

| Trigger | Job | Result |
|---|---|---|
| push to any branch, pull request, manual dispatch | `build` | ISO built twice (identical hashes required), verified, unit/host/boot tests run, assets kept as a workflow artifact |
| push tag `v*` or `pc5-*` | `build`, then `release` | the same, then `pc5.iso`, `pc5.iso.sha256` and `build-info.json` published on the release |

The release job is the only one with `contents: write`, runs only for tags, only
after `build` succeeded, and delegates the publishing to
`tools/publish_release.sh` (checksum gate, verdict gate, create-or-update,
`--clobber`, final asset assertion). That script is unit-tested against a stub
`gh` in `tests/test_release.py`.

## Evidence that exists today, and what does not

* Proven locally: the exact workflow steps run on this machine and produce two
  byte-identical images; the publish script executes correctly against a stub.
* Not proven: that GitHub Actions runs it and accepts the upload — that needs
  the file in `.github/workflows/`, which needs the permission above.

## Activation attempt, 2026-11-12 (milestone B3)

Performed the exact operation described above — `git mv ci/build.yml
.github/workflows/build.yml`, commit, `git push` — against `main` `237725d`.
The push was rejected and nothing reached the remote:

```
 ! [remote rejected] arena/0e2b454e-pc5 -> arena/0e2b454e-pc5 (refusing to allow a GitHub App to create or update workflow `.github/workflows/build.yml` without `workflows` permission)
error: failed to push some refs to 'https://github.com/SpicyBadran/pc5.git'
```

The token is a GitHub App installation token (it reports no OAuth scopes;
`X-Accepted-Github-Permissions: allows_permissionless_access=true`). It holds
`admin`/`push` on this repository, but the GitHub App installation is not
granted the **Workflows** permission, and GitHub refuses to let an App create or
modify anything under `.github/workflows/` without it. Reading the Actions API
confirms the consequence:

```
$ gh api repos/SpicyBadran/pc5/actions/workflows --jq '.total_count'
0
$ gh run list --limit 3
(no output — there are no runs)
```

Zero registered workflows and zero runs: the file has never been read by
GitHub, so no pipeline has ever executed and no release asset has ever been
published (the `pc5-0.1.0` release exists with an empty asset list).

### What the repository owner must do

Grant the Workflows permission to the GitHub App installation for this
repository, then re-run the activation:

1. GitHub → Settings → Applications → (the App that authored these branches) →
   **Configure** → Repository access → ensure `SpicyBadran/pc5` is selected →
   **Permissions → Repository permissions → Workflows: Read and write** → Save.
2. Next session, or by hand:
   ```sh
   git mv ci/build.yml .github/workflows/build.yml
   git commit -m "ci: activate the build and release pipeline"
   git push
   ```

No shell command available in this environment can grant that permission; it is
an installation-level authorization held by the repository owner.
