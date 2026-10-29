---
name: pet-appearance-generator
description: Generate or refine a reusable pet appearance spec and matching pet concept images from text prompts, screenshots, moodboards, or reference art. Use when a user wants to design a desktop pet, virtual mascot, assistant character, animated companion, pet skin, or consistent pet look before animation work. Also use when a user asks to keep a pet's face, palette, silhouette, outfit, or props consistent across multiple pet images or future animation states.
---

# Pet Appearance Generator

Create a stable, reusable pet appearance that can be used later for idle art, action poses, GIFs, spritesheets, or full animation pipelines.

This skill is for appearance design only. It does not own spritesheet assembly, atlas packing, QA contact sheets, animation row extraction, or pet packaging.

## Workflow

1. Establish the appearance goal.
2. Extract the identity anchors.
3. Generate a canonical appearance prompt.
4. Generate one or more appearance images.
5. Review consistency and record the reusable spec.

## Step 1: Establish The Appearance Goal

Identify what the user is actually asking for:

- A brand-new pet look from text only
- A redesign of an existing pet
- A style transfer from one or more references
- A consistency pass so later actions still look like the same pet

If the request is underspecified, infer sensible defaults instead of blocking unless the user is clearly choosing between incompatible directions.

Useful defaults:

- style: compact mascot / desktop pet
- readability: simple silhouette and clear facial features
- complexity: low to medium
- framing: full body, centered, neutral pose
- background: flat removable background

## Step 2: Extract The Identity Anchors

Before generating images, write down the appearance anchors that must remain stable:

- species or creature type
- body proportions
- head shape
- facial expression baseline
- eye shape and eye color
- main palette
- outline style
- outfit or accessory rules
- prop rules
- texture/detail budget
- personality signal

If references are provided, preserve these anchors unless the user explicitly asks for a redesign.

## Step 3: Build The Canonical Appearance Prompt

Produce one concise canonical prompt that can be reused for future generations.

The canonical prompt should describe:

- what the pet is
- its proportions and silhouette
- core palette
- face and expression
- clothing/accessories/props
- rendering style
- background constraints

Keep the prompt visually concrete. Do not pad it with cinematic, glossy, heroic, realistic, or illustration-heavy language unless the user explicitly wants that.

Prefer wording like:

- small desktop pet mascot
- compact chibi proportions
- readable silhouette
- simple clean shading
- consistent face and markings
- front-facing full-body concept pose
- flat plain background for easy extraction

Avoid wording like:

- dramatic lighting
- hyper detailed fur
- realistic anatomy
- cinematic composition
- painterly background
- splash art

## Step 4: Generate The Appearance Images

Use `$imagegen` for normal image generation.

Before generating, read and follow:

```text
${CODEX_HOME:-$HOME/.codex}/skills/.system/imagegen/SKILL.md
```

Do not call the raw image API directly for the normal path.

Generation rules:

- Generate at least one neutral full-body appearance image first.
- If the user wants options, generate 2 to 4 clearly distinct appearance directions, not tiny variations.
- If references exist, attach them with clear role labels.
- Keep the canonical prompt authoritative across all variants.
- Use a plain, removable background unless the user explicitly wants scene art.

Recommended first-pass outputs:

- one canonical neutral pose
- optionally one alternate palette or accessory variant
- optionally one expression variant if it does not change identity

## Step 5: Review And Record The Reusable Spec

After generation, review whether the output is reusable for later animation work.

Reject or revise images that introduce identity drift such as:

- different species feel between variants
- inconsistent face shape
- unstable eye placement or style
- changing prop side without reason
- different palette balance between images
- silhouette clutter
- over-detailed rendering that will not survive animation scaling

When an image is accepted, summarize the reusable appearance spec in plain language so it can be used later for action states.

The summary should include:

- pet name if known
- one-sentence visual description
- stable palette
- stable shape cues
- accessory/prop rules
- forbidden drift

## Output Format

When the user is designing a pet appearance, return:

1. A short appearance summary
2. A canonical generation prompt
3. Any variant notes if multiple directions were explored
4. The generated image result or the handoff to `$imagegen`

Use this structure:

```text
Appearance summary:
<2-4 sentences>

Canonical prompt:
<single reusable prompt>

Consistency rules:
- <rule>
- <rule>
- <rule>
```

## Consistency Rules

When generating follow-up pet images, keep these stable unless the user asks otherwise:

- face shape
- eye design
- main palette
- silhouette
- accessory count
- primary prop
- personality signal

Allowed changes:

- pose
- arm or leg position
- expression intensity
- small secondary prop behavior

Avoid:

- redesigning the pet between images
- changing species cues
- replacing the main prop
- changing the outfit logic
- adding scene-heavy backgrounds
- increasing detail so much that later animation becomes inconsistent

## When To Make Variants

Create variants only when they are meaningfully different, such as:

- different palette family
- different accessory set
- different softness/sharpness of silhouette
- different mascot energy

Do not waste generations on near-duplicate outputs.

## Relationship To Animation Work

If the user later wants action GIFs, spritesheets, or animation folders, use this appearance as the source of truth for those later steps.

This skill should hand off:

- a canonical prompt
- accepted appearance references
- explicit identity anchors

It should not pretend the appearance phase already solved animation timing, frame layout, or action consistency by itself.

## Rules

- Keep this skill focused on appearance generation, not packaging.
- Use `$imagegen` as the primary generation layer.
- Prefer neutral, centered, reusable pet art as the first deliverable.
- Preserve identity anchors across all outputs.
- Keep prompts concise and visually specific.
- Prefer simple readable design over ornate detail for pet work.
- If the user wants an established style, preserve that style instead of forcing a default mascot look.
- If the user wants future animation, optimize the appearance for consistency and silhouette clarity now.

## Acceptance Criteria

- The pet has a clear, reusable visual identity.
- The canonical prompt is specific enough to regenerate the same pet later.
- Palette, silhouette, and face cues are explicitly documented.
- The output image is suitable as a reference for later pose or animation work.
