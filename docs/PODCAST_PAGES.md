# Public podcast delivery

The user authorized the initial three supplied episodes for GitHub Releases/Pages on 2026-11-18. Public deployment is limited to this player, explicit catalog metadata and allowlisted audio derivatives. No question bank, answer history, source script, production prompt, SQLite file or credential is exported.

The user later selected a lightweight client-side access-code curtain whose only goal is to avoid accidental visits during this short-lived personal use. The code is checked by digest in the browser and a matching digest is remembered in `localStorage`; changing the configured digest relocks existing browsers. This is not access control: direct static assets remain public, and no documentation or UI may claim otherwise.

## Initial delivery

1. Bind each selected private source file by SHA-256 in a private publication allowlist. The allowlist stays outside Git. Successful generation or content review does not imply publication permission.
2. tools/podcast_publication.py build checks the source hash/path, preserves originals, and creates a fresh publication bundle. Default AAC 128 kbps preserves original channels. The compressed file must retain the source duration. Results are cached by source hash/encoding profile to preserve immutable audio URLs.
3. Build apps/podcast-public, copy the bundle into its ignored dist directory, then audit with tools/podcast_publication.py audit. Local acceptance additionally checks against the private question bank and checklist through read-only paths. The private application's build auditor continues to reject all audio; the publication auditor accepts only catalog-listed, hash-verified audio.
4. Upload episodes.json and the hash-named audio files as assets of a new podcast-audio-YYYYMMDDTHHMMSSZ Release. This initial format is a complete snapshot; future snapshots select at most 14 eligible episodes. Release assets stay out of Git history. Old Release cleanup is separate from publication and is not automatic.
5. Publish source through .github/workflows/podcast-pages.yml. It builds/tests the public app, selects the latest published podcast audio snapshot (or the supplied release_tag), downloads and checks each asset, and deploys only apps/podcast-public/dist. Deployment is serialized. A failed build leaves the last successful Pages deployment available.

The build uses only the Actions GITHUB_TOKEN for read access and Pages deployment. Google sessions remain on the production machine. Local GitHub publishing uses the official gh CLI and the user's authorization; tokens are never placed in scripts, logs or source.

## Triggers

- Frontend changes: push the scoped public files to main; the workflow path filter triggers a rebuild.
- New approved audio snapshot: upload the Release, then run the podcast-pages.yml workflow with release_tag, or leave it blank for latest. The workflow must exist on the default branch for manual dispatch.
- Future scheduled production: existing local podcast_jobs/worker remains responsible for source selection, NotebookLM stages and safe retries. A publication step may run only after an episode is explicitly eligible for public release. Scheduling and real Google generation require their own setup and evidence; this Pages delivery does not enable them.

Never copy the entire private working tree into a deployment. Prepare a scoped publication checkout and explicit file list. First-launch code publication must preserve the pre-existing dirty application worktree.

## iPhone Safari acceptance

After the public URL returns 200 and each actual media URL supports Range/206:

- Open in Safari, click play once, lock for at least 20 minutes.
- Use lock-screen and Bluetooth headphones to pause/resume and seek; switch apps and test an interruption.
- Seek backward, change speed, close and reopen. Confirm the deliberately rewound position and rate return without autoplay.
- Refresh the catalog, open a single-episode link and test a second tab updating progress.
- Try a network interruption. Existing progress should survive; uncached audio still requires network.

Record actual device/OS/browser and outcomes privately. Desktop playback and a 390px preview are not phone lock-screen acceptance. Public progress is local to the current browser, separate from the private learning system.
