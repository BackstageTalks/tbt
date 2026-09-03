# BlinQ production web fix

Copy these files directly into the repository `web/` directory.

Important fixes in this build:
- production login is bypassed unconditionally;
- CSS and JS use root-absolute URLs so `/follow-the-data/` works;
- asset URLs include a cache-busting version query;
- `ui-config.json` is loaded from `/ui-config.json`;
- API calls remain rooted at `/api/...`.

After committing to `main`, wait for **Deploy BlinQ Web** to finish successfully.
Then open `/follow-the-data/` and hard-refresh once (Ctrl+F5).
