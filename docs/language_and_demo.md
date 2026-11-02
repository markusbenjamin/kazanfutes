# Dashboard language and demo modes

Default: Hungarian, with the existing admin-message behaviour.

- `dashboard.html?lang=en`: English interface.
- `dashboard.html?demo=1`: demo help and no admin message.
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
reopens it by keyboard/touch. Firebase polling cannot reopen dismissed help or
show the real admin message in demo. No storage permissions are needed.

The Hungarian and UK flag links next to help switch the whole dashboard by
reloading with `lang=hu` or `lang=en`. All other URL parameters and the fragment
are preserved, including demo, zoom, mobile and ref_source. Only the non-active
language is shown as a small flag toggle, with a native-language accessible name.
The flag stays visually small on touch screens while retaining a 44px tap target.

English translations are applied at display boundaries before text measurements.
SVG IDs, field names, metric keys, colors, control calculations and proper room/
probe names are not translated. The same canvas.svg is used in both languages
and on touch screens. Dictionary/templated translations live in dashboard_i18n.js.
Kazán 1 and Kazán 2 are proper names of heating circuits on the Kazán side of
the building, not names of the boilers; they remain unchanged in English.
Wind compass letters are localized separately, so the Kelvin unit K stays K.

The config updater publishes both admin_message and admin_message_en from the
same existing Sheet download to system/dashboard in Firebase. Add admin_message_en
as an optional Sheet key/value for English admin text. No automatic translation
or Hungarian fallback is used when that field is absent/blank. Demo and
ref_source=form suppress admin text regardless of language.
