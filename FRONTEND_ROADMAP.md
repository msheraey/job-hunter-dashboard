# JobHunter — Frontend Roadmap
## Filters & Sorters (next Lovable prompt batch)

### Job Matches Page — Sort options
Add a sort bar above the match list (dropdown or segmented control):
- Best Match (default) — sort by `score` desc
- Newest First — sort by `posted_at` desc
- Highest Quality — sort by `quality_score` desc
- Salary (highest) — sort by `salary` field desc (text sort is fine — jobs without salary go to bottom)

### Job Matches Page — Filter panel (collapsible sidebar or top bar chips)
- **By Status**: All (default) | New | Applied | Skipped
- **By Industry**: multi-select chips from INDUSTRY_LIST (Healthcare & Pharmacy, Retail, FMCG, Technology, etc.)
- **By Seniority**: Entry | Mid | Senior | Director (filter by `seniority` field)
- **By Remote**: Onsite | Hybrid | Remote (filter by `remote_status` field)
- **By Visa**: Show only "Visa likely" jobs (filter by `visa_likelihood == "high"`)
- **By Platform**: LinkedIn | Indeed | Bayt | Naukrigulf | GulfTalent (filter by `platform` field)
- **By Score**: slider or preset ranges (60–74% / 75–89% / 90%+)
- **Date posted**: Last 7 days / Last 14 days / All

All filters should be combinable, applied client-side on the current match list (no new API call needed — all data is already in the response).

Show active filter count badge on the filter button. Add a "Clear all filters" link when any filter is active.

### Job Matches Page — Search bar
Simple text search across job title and company name. Client-side, instant.

### Dashboard — Summary stats bar
Above the job cards, show quick totals (pull from the existing match list):
- Total matches today
- Highest score today  
- New since yesterday (compare `posted_at`)
- Applied count (count of applied status)

### Profile / Settings — Title management improvements
- Show how many jobs are in the pool for each tracked title (pull from match data)
- Show last scraped timestamp per title
- Allow drag-to-reorder titles (cosmetic, stored in user prefs)

### Mobile (Capacitor — future)
- Bottom nav bar instead of top nav for mobile
- Swipe left on a job card = Skip, swipe right = Save/Apply (Tinder-style for mobile)
- Push notification permission prompt on first login (wired when NOTIFY_INSTANT=true)

### Analytics Tab (future, data exists in backend)
- Jobs scraped per day (bar chart from scrape_logs)
- Match rate over time (matches/jobs_scored ratio)
- Industry breakdown of matches (pie or donut)
- Top performing job titles (which titles produce most 60%+ matches)
- Application funnel: Seen → Applied → (later: Response received)

---

## Other pending items (non-filter)
- Show `match_reason` prominently — currently added, verify rendering is not truncated on mobile
- "Share job" button on each card (copy link or native share sheet on mobile)
- Job detail expanded view (full description, all classification chips, all intelligence in one place)
- CV version history (store previous CVs, allow rollback)
- Notification settings page: per-channel toggles (when instant alerts activate)
