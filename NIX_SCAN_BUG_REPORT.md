# Nix packages never complete sync — fail at "Scanning Package" with no reason given

## Summary

Every `nix` package pushed to a repository fails to synchronise. The package
is created successfully and its file(s) upload successfully, but the
package's sync pipeline dies at the **"Scanning Package"** stage
(`stage=4`) with `status="Failed"` and **`status_reason: null`** — no
diagnostic is surfaced anywhere in the API response. This reproduces
consistently (2/2 attempts), with or without the optional `narinfo` sidecar
file attached, and is not a timing/flake issue — both failed within 10–15
seconds of upload.

This blocks `nix` package support end-to-end: packages are visible in the
repo's package list, but are stuck in a failed, incomplete state
indefinitely (not downloadable, not synchronised) with no path to
resolution short of manual intervention.

## Environment

- **Instance:** `kharrison.cloudsmith.sh` (personal sandbox)
- **Organization/repo:** `cloudsmith/test-nix-support`
- **API version:** `cloudsmith-api` 2.0.30 (first release exposing
  `NixPackageUploadRequest` / `NixUpstream*` models)
- **Client:** `cloudsmith-cli` branch `kyleharrison/eng-12409/implement-nix-support`
  (commit `bf51ff3`), which adds `nix` to the CLI's supported push/upstream
  formats — see [cloudsmith-cli#365](https://github.com/cloudsmith-io/cloudsmith-cli/pull/365)
- **Auth:** authenticated as `lskillen` (Lee Skillen) via sandbox routing
  headers (`X-Region`, `X-Internal-User-Api-Key`)

> **Update (cloudsmith-api 2.0.31):** the SDK's `narinfo` field was renamed
> to `narinfo_file` (CLI flag is now `--narinfo-file`), and the CLI's
> separate special-casing for the old name was dropped since it now matches
> the generic `_file`-suffix upload convention natively. That resolved a
> distinct CLI-side 422 (see "Why this isn't a CLI bug" below) but is
> unrelated to the "Scanning Package" failure this report is about — the
> commands below use the flag name current at the time of this report
> (`--narinfo`); substitute `--narinfo-file` if reproducing against
> 2.0.31+.

## Steps to reproduce

```bash
# 1. Push a nix package (.nar.xz) with its narinfo sidecar
cloudsmith push nix -W cloudsmith/test-nix-support \
  1asxnrnab7w7jz7ilcbnvn2m3m85c3sx9847ap9hyc9n4jsds04x.nar.xz \
  --narinfo vayna03pzyn98nlz8y4xcb1nncggb4nz.narinfo

# -> Package created OK: slug 1asxnrnab7w7jz7ilcbnvn2m3m85c3sx9847ap9hyc9n4-wr4r
#    (slug_perm 685zgiIVJkip)

# 2. Poll status
cloudsmith status cloudsmith/test-nix-support/685zgiIVJkip -F json
```

Repeated without `--narinfo` (package-file only) for comparison:

```bash
cloudsmith push nix -W cloudsmith/test-nix-support \
  1asxnrnab7w7jz7ilcbnvn2m3m85c3sx9847ap9hyc9n4jsds04x.nar.xz

# -> Package created OK: slug 1asxnrnab7w7jz7ilcbnvn2m3m85c3sx9847ap9hyc9n4-iz3r
#    (slug_perm wSHjxbhNfjjs)
```

Both were also cross-checked via `cloudsmith list packages cloudsmith/test-nix-support -F json`.

## Expected result

The package's sync pipeline completes (`is_sync_completed: true`), or, if it
genuinely cannot be scanned/synced, fails with a populated `status_reason`
explaining why.

## Actual result

Both packages permanently show:

```json
"stage": 4,
"stage_str": "Scanning Package",
"status": 5,
"status_str": "Failed",
"status_reason": null,
"is_sync_completed": false,
"is_sync_failed": true,
"security_scan_status": "Awaiting Security Scan",
"is_security_scannable": false
```

Full package-list entries for both slugs (via `cloudsmith list packages`), trimmed to the relevant fields:

<details>
<summary>slug_perm 685zgiIVJkip (pushed with --narinfo)</summary>

```json
{
  "slug_perm": "685zgiIVJkip",
  "format": "nix",
  "files": [
    {
      "filename": "1asxnrnab7w7jz7ilcbnvn2m3m85c3sx9847ap9hyc9n4jsds04x.nar.xz",
      "tag": "pkg",
      "is_primary": true,
      "is_synchronised": true,
      "size": 54524
    },
    {
      "filename": "vayna03pzyn98nlz8y4xcb1nncggb4nz.narinfo",
      "tag": "narinfo",
      "is_primary": false,
      "is_synchronised": false,
      "size": 522
    }
  ],
  "num_files": 0,
  "is_downloadable": false,
  "is_security_scannable": false,
  "security_scan_status": "Awaiting Security Scan",
  "stage": 4,
  "stage_str": "Scanning Package",
  "status": 5,
  "status_str": "Failed",
  "status_reason": null,
  "sync_progress": 45,
  "uploaded_at": "2026-08-19T13:33:36.656111Z",
  "sync_finished_at": "2026-08-19T13:33:47.005853Z"
}
```
</details>

<details>
<summary>slug_perm wSHjxbhNfjjs (pushed without --narinfo)</summary>

```json
{
  "slug_perm": "wSHjxbhNfjjs",
  "format": "nix",
  "files": [
    {
      "filename": "1asxnrnab7w7jz7ilcbnvn2m3m85c3sx9847ap9hyc9n4jsds04x.nar.xz",
      "tag": "pkg",
      "is_primary": true,
      "is_synchronised": true,
      "size": 54524
    }
  ],
  "num_files": 0,
  "is_downloadable": false,
  "is_security_scannable": false,
  "security_scan_status": "Awaiting Security Scan",
  "stage": 4,
  "stage_str": "Scanning Package",
  "status": 5,
  "status_str": "Failed",
  "status_reason": null,
  "sync_progress": 45,
  "uploaded_at": "2026-08-19T13:36:03.758956Z",
  "sync_finished_at": "2026-08-19T13:36:10.386008Z"
}
```
</details>

## Notable inconsistency (possible root cause lead)

`is_security_scannable: false` on both packages, yet the sync pipeline still
enters (and fails at) a "Scanning Package" stage, while
`security_scan_status` stays at its initial `"Awaiting Security Scan"` and
never progresses. This looks like a **generic malware/content-scan stage
that runs unconditionally for every format**, separate from the
format-gated vulnerability scanner. If that generic scan stage doesn't have
a handler for `.nar.xz` / `.narinfo` content yet, it would plausibly error
out immediately rather than skip — which matches the fast, deterministic
`Failed` we observed (~10–15s, well before any real scan could run) and the
complete absence of a `status_reason`.

Also notable: on the package pushed with `--narinfo`, the primary `.nar.xz`
file reaches `is_synchronised: true`, but the `.narinfo` sidecar file stays
at `is_synchronised: false` — the package fails before ever finishing that
second file, regardless of it having uploaded correctly (checksums for both
files are present and correct in the response).

## Why this isn't a CLI bug

While investigating this, a real CLI bug was found and fixed separately
(`cloudsmith-cli` did not upload the `--narinfo` file via the file-upload
API before sending it to package-create, causing a 422 — fixed in
[#365](https://github.com/cloudsmith-io/cloudsmith-cli/pull/365)). After
that fix, `--narinfo` uploads correctly (see `is_synchronised: true` for the
primary file and a checksummed, attached `.narinfo` entry above) — but the
package still fails identically, **and pushing without `--narinfo` at all
fails the exact same way**. That rules the CLI out as the cause of the
scanning failure: the CLI is uploading files correctly and faithfully
surfacing every field the status API returns; there is no additional detail
being dropped client-side.

## Impact

- `nix` package support cannot ship — no package can reach a synchronised,
  downloadable state on this environment.
- No self-serve diagnosis is possible from the CLI/API side: `status_reason`
  is `null`, so whoever owns the scanning pipeline will need to check
  service-side logs for these package/repo identifiers around the given
  timestamps.

## Suggested next steps

1. Check the package-scanning worker's logs for
   `cloudsmith/test-nix-support` around `2026-08-19T13:33:47Z` (slug_perm
   `685zgiIVJkip`) and `2026-08-19T13:36:10Z` (slug_perm `wSHjxbhNfjjs`) on
   the `kharrison.cloudsmith.sh` sandbox.
2. Confirm whether the generic "Scanning Package" stage has a content
   handler for the `nix` format yet, and whether `is_security_scannable:
   false` for `nix` is intentional (if so, the generic scan stage should
   presumably skip rather than fail for non-scannable formats).
3. Populate `status_reason` for this failure class regardless of the above
   fix, so future format rollouts are debuggable without backend log
   access.
