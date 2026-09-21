# texture_1.txt generator

Adds the `texture:`/`block:` lines (and matching PNGs) for blocks that exist in a Minecraft
client jar but aren't referenced yet in `DynmapCore/src/main/resources/texture_1.txt`, and the
`customblock:` lines in `models_1.txt` for shapes already handled by an existing Java renderer
(stairs, fences, walls, doors, ...).

## Usage

```
python tools/texture_gen/generate_texture_1.py --client-jar path/to/client.jar --dry-run
```

Always run with `--dry-run` first (optionally with `--report out.md` to save the summary) and
read the report before running for real (drop `--dry-run`). Pay special attention to the
"Needs manual review" section: those blocks were deliberately left untouched rather than guessed
at, and a human has to add them by hand.

### Backups / undo

Every real (non-`--dry-run`) run that modifies `texture_1.txt` and/or `models_1.txt` first saves
a `.bak` copy of the file next to the original (e.g. `texture_1.txt.bak`), holding whatever that
file looked like right before this run. If the result isn't what you wanted:

```
python tools/texture_gen/generate_texture_1.py --undo
```

This deletes the current `texture_1.txt`/`models_1.txt` and puts the `.bak` copy back in their
place. It only remembers one run back - running the generator for real again overwrites the
`.bak` with the new "before" state, so `--undo` always reverts the *last* run, not further back.
Pass `--no-backup` to skip saving the `.bak` copy for a given run. Note this only covers the two
`.txt` registries, not the PNGs copied alongside them (those are new files, not overwrites, so
`--undo` leaves them in place).

The jar must be a **client** jar (has `assets/minecraft/textures`, `blockstates`, `models`), not
a server jar - server jars don't ship any of that. A real client jar can be obtained from a
Fabric/Forge dev environment cache (e.g. `~/.gradle/caches/fabric-loom/<version>/minecraft-client.jar`),
a launcher's version folder, or Mojang's piston-meta manifest.

## How it decides what to generate

For each block in the jar not already covered:

1. Resolve its blockstate JSON (`variants` or `multipart`) to the **immediate parent** of each
   model it references (e.g. `stone` -> `cube_all`, `oak_log` -> `cube_column`/`cube_column_horizontal`,
   `oak_fence` -> `fence_post`/`fence_side` via its multipart parts).
2. Combine those parents with the schema (`variants`/`multipart`) and the set of state *property
   names* (not values) into a signature. This is what tells apart, say, a stateless `cube_column`
   block (`chiseled_sandstone`, always the same orientation) from an axis-rotatable one
   (`oak_log`, `deepslate`) even though both ultimately use the `cube_column` model.
3. Leaves are special-cased: a block whose model resolves to `block/leaves` (or whose model has
   `tintindex` on its faces) gets the foliage biome tint (`allfaces=2000:...`); a leaf-like block
   that instead resolves straight to `cube_all` (no tint) does not. The two fixed non-biome tones
   Mojang hardcodes in Java rather than in JSON - spruce ("pine tone") and birch ("birch tone") -
   are the one thing this tool cannot derive from the jar and are kept in `LEAF_TONE_OVERRIDES`;
   extend that table if Mojang ever adds another fixed-tone tree.
4. Otherwise: look through the blocks *already* covered in `texture_1.txt`/`models_1.txt` for one
   with the same signature ("a sibling"), and clone its existing line(s) - substituting only the
   texture names, role for role (e.g. oak_fence's `oak_planks` -> cherry_fence's `cherry_planks`).
   This is deliberate: the tool never re-derives rotation/face geometry itself, it only ever
   reuses geometry a human already got right for an existing block of the same shape. If several
   siblings share a signature (e.g. `oak_log` vs. the bark-everywhere `oak_wood`), the one with
   more distinct textures is preferred, and every candidate is tried until one produces a full,
   conflict-free match.
   - `data=N` selector tokens on the cloned line (legacy: index into the block's own state
     registration order) are always converted to an explicit `state=attrib:val` filter before
     being written out, never copied as `data=N` - trusting a raw registration-order index for a
     *different* block is exactly the bug class this project hit for MC 26.3's default-state
     resolution (barrières/escaliers/dalles waterlogged incorrectly).
   - If a shape's own Java renderer class is used by the sibling (`customblock:` in `models_1.txt`),
     a new one-line `customblock:id=<newblock>,class=<sameclass>` entry is appended too.
5. If no sibling with a matching signature exists yet, or the substitution would be ambiguous
   (conflicting texture roles), the block is skipped and listed under "Needs manual review" -
   the tool never guesses.

New PNGs are copied from the jar into
`DynmapCore/src/main/resources/texturepacks/standard/assets/minecraft/textures/block/`.

## Known cosmetic limitation

Cloned lines keep whichever face-token style (`patch0-2=X` vs. `patch0=X,patch1=X,patch2=X`) the
chosen sibling happened to use - both are equivalent to the Java parser, but the exact wording of
the generated line depends on which existing block was used as a template.

## Verifying after a change to this script

Re-run `--dry-run` against an *older*, already fully-supported client jar (e.g. 1.18.2). Since
every block in it should already be covered, "Cloned"/"Simple" should both come back empty and
only genuinely special-cased blocks (`air`, `item_frame`, ...) should show up under "Needs manual
review" - any other line in those two sections means something regressed.
