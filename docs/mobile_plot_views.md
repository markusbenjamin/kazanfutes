# Touch plot views

On coarse-pointer devices (or the existing `mobile=true` layout), tapping a
supported element pins its ordinary plot and reveals plain-text view tabs:
`alap`, `részletes`, `analitika`. Only available views appear. The selected tab
is underlined; transparent hit rectangles surround the text. No long-press,
double-tap or new zoom gesture is required. Existing pan/pinch behaviour is
preserved. The control is absent on ordinary desktop pointers.

Rooms offer all three views. Piping, cycle dials, radiator targets and the
external thermometer offer ordinary/detailed views. Main/cycle infoboxes and
the boiler offer ordinary/analytics views. Objects without modifier-click
views keep their existing tap behaviour without an extra selector.

Switches reuse existing plot factories and preserve the shown date and
remembered metric, without changing shared ordinary-hover settings. Cycle
analytics retain the cycle filter. Clicking away clears the selected context.
The view row reserves identical space for the foundation and every overlaid
curve, so axes, shading and data stay aligned. Desktop Ctrl/Alt shortcuts and
the default choice on ordinary room hover are unchanged.

The touch selector works with the default SVG used on phones; it does not
automatically opt into the older `canvas_mobile.svg` layout. No backend changes.
