# BooStudy Demo Experience — Visual Canon

This document supplements `BOOSTUDY_UI_CANON.md`; it does not replace it.

## Cinema Mode

- Split composition: Boo and narrative context on one side, interaction card on the other.
- Large, expressive Boo asset; soft educational background; high-contrast dark ink and purple/lilac accents.
- Dialogue card has kicker/chapter, title, body, note, points and tactile CTA.
- Progress communicates chapter position without taking attention away from the current action.
- Interactive answer cards and primary buttons must have clear selected/disabled/focus states.
- The current Chapter 1 uses `boo-onboarding-hero-v2.png` and custom grade select.

## Companion Mode

- Compact Boo or dialogue panel sits beside/over the real platform page.
- It must never obscure the target or make the underlying page impossible to scroll.
- One next action is primary; detours may react but cannot silently lose the canonical route.
- A guided objective uses pulse plus focus hole and follows scroll/resize.
- Reduced-motion mode should avoid smooth movement where possible.
- Regular non-demo students must not receive this layer.

## Reaction mode

Short `say`/status reactions exist for detours and semantic target completion. They should be visually subordinate to a cinematic dialogue but more visible than a passive toast.

## Current assets

| Asset | Use |
|---|---|
| `static/images/demo/boo-onboarding-hero-v2.png` | Chapter 1 hero |
| `static/images/demo/boo-dialogue-v1.png` | dialogue/finale visual |
| `static/images/demo/boo-library-v3.png` | Chapter 4 |
| `static/images/demo/boo-route-v3.png` | Chapter 6 |
| `static/images/demo/onboarding-study-room-v2.png` | onboarding/room visual |
| `static/images/lesson/lesson_task_mascot.png` | trial workspace story |
| `static/images/profile/hero_ghost.png` | Chapter 5 / profile visual |
| `static/images/theory/ghost_rocket.png` | analytics/progress visual |

Asset filenames are confirmed by `boo_companion.js`; visual approval of every binary is not re-established by this snapshot. No single approved external visual reference is treated as canonical beyond the repository assets and `BOOSTUDY_UI_CANON.md`.

## Non-negotiable visual QA

- no text behind Boo;
- no controls that look clickable but do nothing;
- target pulse must surround a visible, actionable element;
- no global overflow lock during a guided task;
- mobile must preserve target visibility and readable dialogue;
- icon font failures must not remove semantic labels.
