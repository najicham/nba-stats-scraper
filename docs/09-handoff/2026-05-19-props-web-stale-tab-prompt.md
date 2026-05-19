# Props-web stale-tab investigation — prompt for a fresh session

Open a new Claude Code session in `~/code/props-web` and paste everything below the line.

---

I'm investigating a Tonight-page stale-tab bug on playerprops.io. Reproduction:

1. Open the site, click Best Bets → load fine.
2. Leave the tab idle for hours (24h in this case).
3. Come back, click Tonight tab → loader spins forever, no transition.
4. Hard refresh, then click Tonight → works.

Console output during the bad state (most of it is noise, the signal is the Firebase line):

```
Failed to load resource: the server responded with a status of 400 ()
FirebaseError: Installations: Create Installation request failed with error
  "400 INVALID_ARGUMENT: Request contains an invalid argument." (installations/request-failed).
Unchecked runtime.lastError: A listener indicated an asynchronous response by returning true,
  but the message channel closed before a response was received
Could not establish connection. Receiving end does not exist.
```

The `runtime.lastError` and `Could not establish connection` lines are browser-extension noise — ignore. The Firebase 400 is real but probably orthogonal to the navigation hang (Installations is for Analytics/FCM/Remote Config, not for page rendering).

## Primary hypothesis: stale Next.js route chunk

A Vercel deploy probably landed while my tab was open. Next.js prefetches route bundles by content hash; when the deploy invalidates those hashes, clicking Tonight tries to load a JS chunk that returns 404, and there's no error fallback so the loader just spins.

## What to check

1. `next.config.js` / `next.config.mjs` — is `generateBuildId` set? Is there any handling for stale chunks?
2. The Tonight page route handler — what fetches the data? Is there a timeout? An `error.tsx` boundary? A retry on chunk-load-error?
3. Is there a Service Worker (PWA, Workbox, `next-pwa`)? If yes, does it have `skipWaiting + clientsClaim`? Stale SW can serve dead chunks for hours.
4. Search for `ChunkLoadError` handling — anywhere in `_app.tsx`, error boundaries, or a `window.onerror` hook. Next 13+ has a known issue where ChunkLoadError on navigation silently hangs without `router.events` handling.
5. Firebase init: where is `firebaseConfig` defined? Check `apiKey` against the GCP Console restrictions. If `playerprops.io` isn't on the API-key referrer allowlist, Installations 400s. But this is a separate fix from the loader-hang.
6. Git log: any deploys to main in the last 48h? Cross-reference with when the loader-hang started.

## Likely fixes (rank after investigation)

- **Auto-reload on ChunkLoadError**: catch `ChunkLoadError` globally and `window.location.reload()`. The standard pattern is in `_app.tsx` or via Next.js's `onRouterError`.
- **Build-version poll**: ship a `/version.json` with the current build ID, poll every N minutes, soft-reload if stale.
- **Service Worker skipWaiting**: if there's a SW, ensure it activates new versions immediately.
- **Firebase API key referrers**: separate fix in GCP Console → APIs & Services → Credentials. Add `*.playerprops.io/*`, `playerprops.io/*` to the allowlist. Doesn't fix the loader hang but cleans up the console.

## What I want from you

1. Read the relevant files and confirm/refute the stale-chunk hypothesis.
2. Identify what's missing (ChunkLoadError handler? build-version poll? SW config?).
3. Recommend a fix with rough scope (one PR vs multi-step).
4. Don't ship code yet — propose, get my sign-off, then implement.

Context: this site is a personal NBA/MLB betting tool. I'm the only operator. Production is on Vercel. The bug is "annoying but not blocking" — refresh works — so don't rush a hotfix; root-cause it.
