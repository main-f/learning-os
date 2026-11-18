# Learning OS public podcasts

Static React/Vite player for explicitly published episodes. It fetches only episodes.json and content-addressed media from the same site. The private learning API, bank, source packs and results are not dependencies of this entry point.

Run npm ci, npm test and npm run build in this directory. PODCAST_BASE_PATH defaults to /learning-os/; the Pages workflow sets it from the repository name. Local playback helpers are shared through packages/podcast-playback.

The catalog schema is validated in src/catalog.ts. Browser-local position and speed survive reopening and support intentional rewinds. No account, server-side progress synchronization or offline cache is claimed. Audio starts only after a click. Media Session actions are feature-detected; actual iPhone Safari lock-screen playback requires device acceptance.

The publisher creates a fresh snapshot containing at most 14 explicitly allowlisted episodes. Each file has an immutable SHA-256 name. A GitHub Release stores the audio and catalog; the Pages workflow verifies the snapshot, builds this app and publishes only dist. Audio never enters Git history.

Publication tools and operational steps: ../../docs/PODCAST_PAGES.md from the repository root documentation. Google authentication/production are separate from publishing.
