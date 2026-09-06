# Google Search Acquisition Plan

This plan connects Sightline's public search pages, Google Ads campaigns, GA4 conversion events and Search Console feedback into one acquisition loop.

## Positioning

Sightline should not compete for broad terms such as `humanitarian aid`, `crisis news` or `AI writing`. Those searches have mixed intent and weak product fit.

The initial acquisition wedge is operational work with clear software intent:

- Humanitarian situation report preparation
- Crisis evidence collection for reporting
- Humanitarian donor proposal drafting
- ECHO, USAID/BHA and OCHA CBPF proposal workflows

The public crisis pages build trust and capture research intent. The solution pages convert users who are looking for a reporting or proposal tool.

## Landing pages

| Intent | Final URL | Primary action | Secondary action |
|---|---|---|---|
| SITREP creation | `/solutions/sitrep` | `create_sitrep` | `view_crisis_data` |
| Proposal preparation | `/solutions/proposal` | `open_proposal` | `view_crisis_data` |
| Country crisis research | `/crisis/<country>` | `make_sitrep` | Internal evidence links |

Do not send paid traffic directly to a generic dashboard when a matching solution page exists. Keep the user's original Google Ads parameters through the first request and avoid redirects that remove the GCLID.

## Initial Google Ads structure

Start with Search campaigns only. Keep SITREP and Proposal intent in separate campaigns so spend, search terms and conversions remain interpretable.

### Campaign: Humanitarian SITREP Software

Ad group: Situation report software

- `[humanitarian situation report software]`
- `"humanitarian situation report software"`
- `[sitrep generator]`
- `"AI situation report generator"`
- `"humanitarian reporting tool"`

Ad group: Crisis reporting workflow

- `"crisis report generator"`
- `"humanitarian crisis reporting software"`
- `"secondary data review humanitarian"`
- `"humanitarian data analysis tool"`

Final URL: `/solutions/sitrep`

### Campaign: Humanitarian Proposal Software

Ad group: Proposal writing software

- `[humanitarian proposal writing software]`
- `"NGO proposal writing software"`
- `[donor proposal software]`
- `"humanitarian grant writing software"`

Ad group: Donor-specific workflow

- `"ECHO proposal software"`
- `"USAID BHA proposal tool"`
- `"OCHA CBPF proposal tool"`
- `"SMART indicator checker humanitarian"`

Final URL: `/solutions/proposal`

Begin with exact and phrase match. Broad match should be tested only after real conversion data and a reliable negative-keyword process exist.

## Initial negative-keyword list

Apply an account-level list for clearly irrelevant intent:

- jobs
- salary
- internship
- course
- certification
- definition
- meaning
- military
- army
- police
- school assignment
- PowerPoint
- torrent

Do not exclude `template`, `example`, `free` or country names globally. They can carry relevant humanitarian research or evaluation intent. Review them through the search terms report and apply campaign-level exclusions only when the observed queries are irrelevant.

## Conversion model

Primary conversion for bidding:

- `sign_up`

Secondary observation events:

- `create_sitrep`
- `open_proposal`
- `make_sitrep`
- `login`
- `login_prompt_view`

CTA clicks are useful funnel signals but should not be treated as equivalent to a new account. Import validated GA4 key events into Google Ads, keep CTA events secondary at launch, and prevent the same user action from being counted by both a native Ads tag and an imported GA4 event.

## Campaign copy guardrails

Approved factual themes:

- Build cited situation reports from trusted humanitarian sources.
- Review evidence, dates and generated sections before export.
- Draft donor proposals through a guided workflow.
- Check SMART indicators and cross-section consistency.

Do not claim real-time coverage, official warning status, guaranteed funding, automatic donor compliance or field-level verification.

## Example responsive search ad copy

### SITREP campaign

Headlines:

- Humanitarian SITREP Software
- Build Reports From Evidence
- Keep Sources and Dates Visible
- Review Before You Export
- Sightline SITREP

Descriptions:

- Build cited humanitarian situation reports from trusted sources in a guided, reviewable workflow.
- Collect crisis evidence, structure findings and review every section before operational use.

### Proposal campaign

Headlines:

- Humanitarian Proposal Software
- Build Donor-Ready Drafts
- Check SMART Indicators
- Keep Sections Consistent
- Sightline Proposal Studio

Descriptions:

- Draft humanitarian proposals with guided structure, evidence support and quality checks.
- Connect objectives, activities and indicators, then export a draft for team review.

## Launch gates

Do not spend until every item below is verified:

1. GA4 consent behavior works on both solution pages.
2. `sign_up`, CTA and login events appear with correct parameters in DebugView.
3. GA4 and Google Ads are linked.
4. Google Ads auto-tagging is enabled and a test landing request retains the GCLID.
5. `sign_up` is imported once as the primary conversion.
6. CTA conversions remain secondary observation actions.
7. Search Console property access and weekly snapshot sync are working.
8. Geographic targeting matches the actual sales and support scope.
9. Daily spend and account-level billing alerts are explicitly set by the account owner.
10. Privacy and consent behavior is reviewed in the target regions.

## Weekly operating loop

1. Review Google Ads search terms and add only evidence-backed negatives.
2. Compare paid landing-page sessions with `sign_up` and qualified CTA events.
3. Review Search Console top queries, pages, CTR and average position.
4. Improve titles or page copy where impressions are present but CTR is weak.
5. Expand country or theme content only when Search Console shows real demand.
6. Keep campaign and landing-page changes isolated long enough to measure their effect.

## Source references

- [Google Ads keyword matching](https://support.google.com/google-ads/answer/14996023)
- [Google Ads negative keyword lists](https://support.google.com/google-ads/answer/2453983)
- [Import GA4 key events into Google Ads](https://support.google.com/google-ads/answer/2375435)
- [Google Ads auto-tagging](https://support.google.com/google-ads/answer/7688384)
- [Search Console Search Analytics API](https://developers.google.com/webmaster-tools/v1/searchanalytics/query)
