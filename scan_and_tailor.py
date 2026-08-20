#!/usr/bin/env python3
"""
Runs on a schedule via GitHub Actions (see .github/workflows/scan.yml).
1. Polls each configured company's Greenhouse/Lever job board (public JSON APIs).
2. Filters postings against entry-level keywords.
3. For any NEW match (not seen in a previous run), calls Claude to tailor
   the resume to that specific job description.
4. Writes everything to data/jobs.json, which the static index.html reads.

Nothing here runs in a browser, so there is no CORS restriction - this can
reach any board that exposes a public API. Boards without a public API
(most large enterprise ATSs - Workday, SuccessFactors, custom portals) are
NOT covered here; see README.md for why and what to do about it.
"""

import json
import os
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).parent
COMPANIES_FILE = ROOT / "companies.json"
JOBS_FILE = ROOT / "data" / "jobs.json"
SEEN_FILE = ROOT / "data" / "seen.json"

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
RESUME_TEXT = os.environ.get("RESUME_TEXT", "")

DEFAULT_KEYWORDS = [
    "entry level", "entry-level", "junior", "associate", "graduate",
    "trainee", "intern", "level 1", "l1", "support", "qa", "analyst",
    "fresher", "0-1 year", "0-2 year"
]
KEYWORDS = [k.strip().lower() for k in os.environ.get("KEYWORDS", ",".join(DEFAULT_KEYWORDS)).split(",") if k.strip()]


def log(msg):
    print(f"[{datetime.now(timezone.utc).isoformat()}] {msg}", flush=True)


def http_get_json(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "job-scan-agent/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def strip_html(html):
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch_greenhouse(token):
    data = http_get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true")
    out = []
    for j in data.get("jobs", []):
        out.append({
            "id": f"gh_{j['id']}",
            "title": j.get("title", ""),
            "location": (j.get("location") or {}).get("name", ""),
            "link": j.get("absolute_url", ""),
            "jd": strip_html(j.get("content", "")),
        })
    return out


def fetch_lever(token):
    data = http_get_json(f"https://api.lever.co/v0/postings/{token}?mode=json")
    out = []
    for j in data:
        out.append({
            "id": f"lv_{j.get('id')}",
            "title": j.get("text", ""),
            "location": (j.get("categories") or {}).get("location", ""),
            "link": j.get("hostedUrl", ""),
            "jd": j.get("descriptionPlain") or j.get("description", ""),
        })
    return out


def matches_keywords(title, jd):
    if not KEYWORDS:
        return True
    hay = (title + " " + (jd or "")[:600]).lower()
    return any(k in hay for k in KEYWORDS)


def tailor_with_claude(job):
    if not ANTHROPIC_API_KEY:
        log("No ANTHROPIC_API_KEY set - skipping tailoring, saving job without a tailored resume.")
        return None
    if not RESUME_TEXT or len(RESUME_TEXT.strip()) < 30:
        log("No RESUME_TEXT secret set - skipping tailoring.")
        return None

    system_prompt = (
        "You are helping tailor a one-page resume to a specific job description for an "
        "entry-level candidate. Return ONLY valid JSON, no markdown fences, no preamble, "
        "matching exactly this shape: "
        '{"tailored_resume": "full tailored resume as plain text, same overall length as the '
        "original, reordered/reworded to foreground the most relevant experience for this JD, "
        "never inventing skills or experience not present in the original\", "
        '"key_changes": ["short bullet describing a change made", "..."], '
        '"gap_flags": ["short honest bullet naming a real requirement in the JD the candidate\'s '
        'resume does not support - empty array if none"]}. '
        "Do not fabricate qualifications, tools, or years of experience the candidate doesn't have. "
        "If the JD needs something missing, note it in gap_flags rather than inventing it."
    )
    user_msg = (
        f"BASE RESUME:\n{RESUME_TEXT}\n\n"
        f"JOB TITLE: {job['title']}\nCOMPANY: {job['company']}\n\n"
        f"JOB DESCRIPTION:\n{job['jd'][:4000]}"
    )

    body = json.dumps({
        "model": "claude-sonnet-4-6",
        "max_tokens": 2000,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_msg}],
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = "".join(b.get("text", "") for b in data.get("content", []))
        clean = re.sub(r"```json|```", "", text).strip()
        return json.loads(clean)
    except Exception as e:
        log(f"Tailoring failed for {job['title']} @ {job['company']}: {e}")
        return None


def main():
    companies = json.loads(COMPANIES_FILE.read_text())
    seen = set(json.loads(SEEN_FILE.read_text())) if SEEN_FILE.exists() else set()
    existing_jobs = json.loads(JOBS_FILE.read_text()) if JOBS_FILE.exists() else []
    existing_by_id = {j["id"]: j for j in existing_jobs}

    new_count = 0
    for c in companies:
        try:
            log(f"Polling {c['name']} ({c['platform']}:{c['token']})")
            if c["platform"] == "greenhouse":
                jobs = fetch_greenhouse(c["token"])
            elif c["platform"] == "lever":
                jobs = fetch_lever(c["token"])
            else:
                log(f"Unknown platform for {c['name']}, skipping")
                continue
        except (urllib.error.URLError, urllib.error.HTTPError, Exception) as e:
            log(f"Could not reach {c['name']}: {e}")
            continue

        for j in jobs:
            if not matches_keywords(j["title"], j["jd"]):
                continue
            job_id = j["id"]
            if job_id in seen:
                continue  # already processed in a previous run
            j["company"] = c["name"]
            log(f"New match: {j['title']} @ {c['name']}")
            tailored = tailor_with_claude(j)
            record = {
                "id": job_id,
                "title": j["title"],
                "company": c["name"],
                "location": j["location"],
                "link": j["link"],
                "found_at": datetime.now(timezone.utc).isoformat(),
                "tailored_resume": tailored["tailored_resume"] if tailored else None,
                "key_changes": tailored["key_changes"] if tailored else [],
                "gap_flags": tailored["gap_flags"] if tailored else [],
            }
            existing_by_id[job_id] = record
            seen.add(job_id)
            new_count += 1

    all_jobs = sorted(existing_by_id.values(), key=lambda r: r["found_at"], reverse=True)
    JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
    JOBS_FILE.write_text(json.dumps(all_jobs, indent=2))
    SEEN_FILE.write_text(json.dumps(sorted(seen)))
    log(f"Done. {new_count} new match(es) this run. {len(all_jobs)} total tracked.")


if __name__ == "__main__":
    main()
