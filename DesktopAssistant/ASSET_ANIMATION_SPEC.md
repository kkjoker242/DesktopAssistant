# Desktop Assistant Animation Asset Spec

This document records the current animation asset contract for the PySide6 desktop pet.
The active character is loaded from `assets/animated/whale-girl/`.

## Required Actions

The application currently loads these six actions:

1. `idle`
Light breathing motion. Small vertical body movement is enough.

2. `blink`
One complete blink cycle for random insertion during idle and rest states.

3. `walk`
Looped walk cycle. Arms and legs should alternate naturally.

4. `wave`
Greeting or response gesture. Used for click interaction and reply completion.

5. `think`
Slight head tilt or hand-to-face motion. Used while the assistant is waiting for a reply.

6. `rest`
Relaxed state, such as closed eyes or a small yawn.

## Current Frame Counts

- `idle`: 3 frames
- `blink`: 3 frames
- `walk`: 3 frames
- `wave`: 3 frames
- `think`: 3 frames
- `rest`: 3 frames

Each action is stored as numbered transparent PNG frames (`00.png` through `02.png`).

## Canvas And Layout Rules

- Current exported frame size: `384x384`
- Keep the character centered across all frames
- Keep the character scale identical across all actions
- Keep the foot baseline stable to avoid visible jumping
- Maintain similar top, left, and right padding across frames
- Do not crop hair, hands, or boots at the image edge
