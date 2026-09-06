# Measurement and Advertising

Sightline uses one consent-aware measurement contract across the landing page, public SEO pages, and the authenticated application.

## Runtime behavior

- Analytics is disabled when `GOOGLE_ANALYTICS_ID` is empty.
- With an ID configured, `/static/analytics.js` presents an analytics choice before loading the Google tag.
- Declining sends no Analytics request and stores only the local preference.
- Accepting loads GA4 with Analytics storage granted and advertising storage, advertising user data, advertising personalization, Google Signals, and ad-personalization signals disabled.
- A visitor can reopen the choice from any `Privacy choices` link.
- AdSense is disabled unless `GOOGLE_ADSENSE_CLIENT`, `GOOGLE_ADSENSE_SLOT_ID`, and `GOOGLE_ADSENSE_CMP_READY=true` are all configured.
- `GOOGLE_ADSENSE_CMP_READY` must remain false until a Google-certified CMP is configured and verified for the site. The local Analytics choice is not a replacement for an AdSense-certified CMP.
- AdSense is not included in the authenticated application and its public-page loader suppresses ad slots when a Sightline sign-in token is present.

## GA4 event contract

| Event | Parameters | Meaning |
|---|---|---|
| `page_view` | Standard GA4 parameters | Automatically sent after Analytics consent on a page load |
| `cta_click` | `cta_name`, `cta_location`, `link_url`, `page_path` | A marked acquisition or product CTA was selected |
| `navigation_click` | `link_url`, `link_location`, `page_path` | Cross-surface or outbound navigation from the application |
| `tab_view` | `tab_name`, `page_path` | Virtual navigation inside the single-page application |
| `login_prompt_view` | `page_path` | An anonymous visitor reached an authenticated feature gate |
| `login_start` | `method` | A sign-in flow started |
| `login` | `method` | A sign-in flow completed |
| `sign_up` | `method` | A first-time account creation completed |
| `login_error` | `method`, `error_code` | A sign-in flow failed without sending the error message or identity data |

Recommended GA4 key events after validation:

- `cta_click` where `cta_name` is `start_free` or `make_sitrep`
- `login`
- `sign_up`

Import key events into Google Ads only after GA4 and Google Ads are linked and DebugView confirms that parameter values are correct.

## Required account-side setup

1. Configure the production GA4 Measurement ID.
2. Validate consent changes, page views, and named events in GA4 DebugView.
3. Link the GA4 property to Google Search Console and Google Ads.
4. Mark `sign_up` and the validated qualified CTA events as GA4 key events, then import them into Google Ads as conversion actions.
5. Keep Google Ads auto-tagging enabled. Use public, indexable landing-page URLs as final URLs; GA4 handles attribution for visitors who accept Analytics without custom URL rewriting.
6. Before enabling AdSense, configure a Google-certified CMP through AdSense Privacy & messaging or another certified provider.
7. Set `GOOGLE_ADSENSE_CMP_READY=true` only after the CMP message and regional behavior are verified.

## Search Console reporting

Sightline can store a weekly, read-only Search Console snapshot in `growth.db`. The sync records property totals plus the leading query and page pairs for a finalized reporting period.

1. Enable the Search Console API in the Google Cloud project used by the service account.
2. Add the service-account email as a user of the exact Search Console property.
3. Set `GSC_SITE_URL` to the property identifier, for example `sc-domain:sightlinehumanitarian.com`.
4. Configure `GSC_CREDENTIALS_PATH` and set `GSC_ENABLED=true`.
5. Run `python scripts/sync_search_console.py` once and verify the Search Console section in Admin Analytics.

The Search Analytics API can return only leading rows rather than every row. Property totals therefore come from a separate aggregate request and must not be reconstructed by summing the displayed query table.

References: [Google Consent Mode](https://developers.google.com/tag-platform/security/concepts/consent-mode), [AdSense CMP requirements](https://support.google.com/adsense/answer/13554116), [Search Console Search Analytics API](https://developers.google.com/webmaster-tools/v1/searchanalytics/query).
