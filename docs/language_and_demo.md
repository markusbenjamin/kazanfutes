# Dashboard language and demo modes

Default: Hungarian, with the existing admin-message behaviour.

- `dashboard.html?lang=en`: English interface.
- `dashboard.html?demo=1`: demo help where enabled.
- `dashboard.html?lang=en&demo=1`: English demo.

Existing query parameters (zoom, centered element, mobile, ref_source) may be
combined with either mode. `demo=true` is also accepted. Demo uses the real
dashboard data; it does not simulate sensors, alter controls or write data.

English help is available via the small `help` button at the top right.
Hungarian `mi ez?` help is temporarily disabled, including automatic opening in
demo mode. Its content/code is retained behind `HUNGARIAN_DASHBOARD_HELP_ENABLED`
in dashboard_help.js. English help opens automatically only in demo
mode. The help box is yellow, in the admin message's position, but is a separate
dialog; admin messages remain pink. Ok, X or Escape closes help, and the button
reopens it by keyboard/touch. Firebase polling cannot reopen dismissed help.
Messages also work in demo and form-referral views. No storage permissions are needed.

The `hu` and `en` text links next to help switch the whole dashboard in place,
updating `lang=hu` or `lang=en` without navigation. All other URL parameters and the fragment
are preserved, including demo, zoom, mobile and ref_source. Only the non-active
language is shown as a compact text toggle, with a native-language accessible name.
The link stays visually small on touch screens while retaining a 44px tap target.
Plots redraw from their retained inputs, preserving the date, selected metric,
pinning, zoom and active replay position/playback. Static SVG text retains its
Hungarian source for reversible relabeling. Help does not reopen on a switch;
acknowledgements of configured messages survive switching languages.

English translations are applied at display boundaries before text measurements.
SVG IDs, field names, metric keys, colors, control calculations and proper room/
probe names are not translated. The same canvas.svg is used in both languages
and on touch screens. Dictionary/templated translations live in dashboard_i18n.js.
Kazán 1 and Kazán 2 are proper names of heating circuits on the Kazán side of
the building, not names of the boilers; they remain unchanged in English.
Wind compass letters are localized separately, so the Kelvin unit K stays K.

## Configured dashboard messages

The dashboard reads these fields directly from the first tab of the existing
heating-control config Sheet, on page load and every 30 seconds. The Sheet must
allow anyone with its link to view it. No API key, Google login, Pi restart or
GitHub config-copy refresh is required for message updates.

| Message | Text | Priority |
| --- | --- | --- |
| Admin | `admin_message` | `admin_message_priority` |
| Rain protection | `rain_protection_message` | `rain_protection_message_priority` |
| Boiler error | `boiler_fault_message` | `boiler_fault_message_priority` |

English text uses `admin_message_en`, `rain_protection_message_en` and
`boiler_fault_message_en`. There is no automatic translation or Hungarian fallback;
an absent/blank text in the selected language is hidden, with no built-in replacement.

All messages share the centered pink dialog, formatting and Ok/X/Escape controls.
The lowest numeric priority among active, nonempty messages wins (1 before 2 before 3).
Missing or invalid priorities rank last; equal priorities use rain, boiler, admin order. Admin
messages are always eligible. Boiler errors follow the nonempty `system/state/boiler_error`
string; rain protection follows the fresh, running `system/state/rain_protection.rain_shutdown` latch.
Both conditions make the boiler black independently of message text or priority.
Only these operational states come from Firebase; its message text/config copy
cannot overwrite the directly downloaded Sheet values. During a failed Sheet
request, the last successfully read messages remain in effect.

Acknowledging a message keeps it closed across polling and does not reveal
lower-priority messages while it remains the selected condition. A changed text,
reload, or cleared-and-recurring error permits it to show again. Pending admin
text returns after higher-priority errors clear, unless already acknowledged.

## Plot loading messages

A newly selected plot/day/filter gets a ten-second grace period before an
empty-data message appears. During it the plot says `Adatok betöltése.` /
`Loading data.`; real data replaces the placeholder immediately. If the plot
is still empty after ten seconds, its specific unavailable-data message appears.
Polling/redrawing the same view does not restart the grace period. Changing
views cancels the old deadline, and timers update only still-connected empty
labels, never redraw over a successfully loaded curve. The presentation-only
helper lives in plot_loading.js; it does not alter the downloaded data.
