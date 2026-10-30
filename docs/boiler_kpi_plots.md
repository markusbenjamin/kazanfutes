# Boiler analytics

Alt+click the boiler, or use `analitika` on touch. `hőhasznosítás` retains the
existing daily ratio chart. The trial `napi pontok` view has one point per day in
the same seven-calendar-day window ending on the selected day.

X is daily delivered heat (the four cycle energy counters summed, kWh); Y is
100 times that sum divided by the day's gas energy. Both views reuse
`boilerDailyKPI`, its common cycle cutoff and gas reading at or before that
cutoff, and the existing 34 MJ/m³ gas conversion. This is a ratio of accumulated
energies, never an average of instantaneous ratios. Today is partial-day data.
Missing cycle streams are not zero. A zero/absent gas denominator yields no
point; a real zero delivered heat with positive gas is a valid zero-percent
point. Values above 100% are not clipped.

Points are black, except the selected day's larger red point, drawn last. Hover
shows date, delivered heat, gas energy and the ratio. There are no connecting
lines or density interpolation. The faint dashed horizontal guide marks 100%.
Shared date arrows shift the window; switching analytics tabs preserves the
selected day/window, and the chosen tab is remembered within the page session.
Late responses cannot repaint another date or analytics tab. No new formatter,
logs, polling stream or Firebase fields are introduced.
