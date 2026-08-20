# Signal — automatic job scan + resume tailoring

Runs on a schedule on GitHub's servers. You don't need to keep anything open —
it checks job boards every 4 hours, tailors your resume with Claude for any
new entry-level match, and writes the results to a page you can check whenever.

## What it actually covers (read this first)

- **Automatic, real-time:** any company on **Greenhouse** or **Lever** — their
  public JSON APIs are what makes unattended polling possible. `companies.json`
  ships with 3 verified boards; add more the same way (find the token in the
  board's URL, e.g. `boards.greenhouse.io/<token>` or `jobs.lever.co/<token>`).
  You can also just paste a company name to me in chat and I'll look up the
  token and add it for you.
- **Not covered:** TCS, Cognizant, Salesforce, GlobalLogic, Concentrix, and
  most large enterprise career sites. This isn't a CORS issue here (this
  script runs server-side, not in a browser) — it's that those sites use
  JS-rendered portals (Workday, SuccessFactors, custom) with no public API,
  actively resist bots, and scraping them at a schedule risks your requests
  getting blocked or violating their terms of service. If you want those
  covered periodically, ask me in chat to sweep them and I'll do it live with
  my own web access and add results in by hand.

## One-time setup (~10 minutes)

1. **Create a GitHub repo.** Push these files to it (or upload via the GitHub
   web UI — "Add file" → "Upload files").
2. **Get an Anthropic API key.** Go to console.anthropic.com → API Keys →
   create one. This is separate from your claude.ai login, and costs a small
   amount per resume tailored (a few cents each) — pay-as-you-go on that
   account.
3. **Add two repo secrets** (repo → Settings → Secrets and variables →
   Actions → New repository secret):
   - `ANTHROPIC_API_KEY` — the key from step 2
   - `RESUME_TEXT` — paste your full resume as plain text
4. **Enable GitHub Actions** if prompted (repo → Actions tab → enable
   workflows). The scan runs every 4 hours automatically, or click
   **"Run workflow"** on the Actions tab to trigger it immediately.
5. **Enable GitHub Pages** (repo → Settings → Pages → Source: "Deploy from a
   branch" → branch `main`, folder `/ (root)`). GitHub gives you a URL like
   `https://<username>.github.io/<repo>/` — that's your site.

## Important: this page is not private

GitHub Pages sites are reachable by anyone who has the URL, even from a
private repo, unless you're on GitHub Enterprise. Your résumé's contact
details will appear in the tailored output on that page. Two reasonable
options:
- Don't share the URL, and accept that it's obscurity rather than real
  privacy (the same as most resume-sharing services).
- Strip your phone/email from `RESUME_TEXT` and add them back manually after
  you copy a tailored resume, before applying.

## Adjusting things later

- **Scan frequency:** edit the `cron` line in `.github/workflows/scan.yml`.
- **Keywords:** add a `KEYWORDS` repo secret (comma-separated) to override
  the defaults in `scan_and_tailor.py`.
- **More companies:** edit `companies.json`, commit, done.
