#!/usr/bin/env python3
"""
Generates new texture_1.txt / models_1.txt entries (+ copies the matching PNGs) for
blocks that exist in a given Minecraft client jar but are not yet referenced in
texture_1.txt.

Usage:
    python generate_texture_1.py --client-jar path/to/client.jar [--dry-run] [--report out.md]

Before actually writing (i.e. whenever --dry-run is NOT given), a .bak copy of
texture_1.txt/models_1.txt is saved next to the original before it's modified, so a
run that turns out not to be what you wanted can be undone:

    python generate_texture_1.py --undo

--undo deletes the current texture_1.txt/models_1.txt and puts the .bak copy back in
their place. It only remembers one level back (the state right before the *last* real
run) - running the generator for real again overwrites the .bak with that new "before"
state. Pass --no-backup to skip saving the .bak copy for a given run.

See tools/texture_gen/README.md for how the classification/cloning strategy works.
"""
import argparse
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TEXTURE_1 = REPO_ROOT / "DynmapCore/src/main/resources/texture_1.txt"
MODELS_1 = REPO_ROOT / "DynmapCore/src/main/resources/models_1.txt"
TEXTURE_1_BACKUP = TEXTURE_1.with_name(TEXTURE_1.name + ".bak")
MODELS_1_BACKUP = MODELS_1.with_name(MODELS_1.name + ".bak")
BLOCK_TEXTURES_DIR = REPO_ROOT / "DynmapCore/src/main/resources/texturepacks/standard/assets/minecraft/textures/block"

# Fixed biome-tint face-index prefixes (see texture_1.txt header comment). Not derivable from
# the client jar: vanilla hardcodes these per-species tones in Java (BlockColors), not in JSON.
FOLIAGE_TINT_PREFIX = 2000
LEAF_TONE_OVERRIDES = {
    "spruce_leaves": 13000,  # "pine tone"
    "birch_leaves": 14000,   # "birch tone"
}

FACE_TEXTURE_RE = re.compile(r"^([A-Za-z][\w\-]*)=(\d+):([A-Za-z0-9_]+)$")
BLOCKCOLOR_RE = re.compile(r"^blockcolor=([A-Za-z0-9_]+)$")


def strip_ns(ref):
    """'minecraft:block/oak_planks' -> 'block/oak_planks'."""
    return ref.split(":", 1)[1] if ":" in ref else ref


def leaf_name(texture_ref):
    """'minecraft:block/oak_planks' -> 'oak_planks'."""
    return strip_ns(texture_ref).rsplit("/", 1)[-1]


def state_str_to_dynmap(state_str):
    """'axis=y' -> 'axis:y'; 'facing=north,half=bottom' -> 'facing:north/half:bottom'."""
    if not state_str:
        return None
    parts = [p.split("=", 1) for p in state_str.split(",") if "=" in p]
    return "/".join(f"{k}:{v}" for k, v in parts)


class ModelCache:
    """Lazily loads and caches assets/minecraft/models/block/*.json from the jar."""

    def __init__(self, zf):
        self.zf = zf
        self._cache = {}

    def load(self, model_ref):
        key = strip_ns(model_ref)
        if key not in self._cache:
            try:
                self._cache[key] = json.loads(self.zf.read(f"assets/minecraft/models/{key}.json"))
            except KeyError:
                self._cache[key] = {}
        return self._cache[key]

    def immediate_parent(self, model_ref):
        parent = self.load(model_ref).get("parent")
        return strip_ns(parent) if parent else None

    def own_textures(self, model_ref):
        textures = self.load(model_ref).get("textures", {})
        return {k: leaf_name(v) for k, v in textures.items() if isinstance(v, str) and not v.startswith("#")}

    def has_tintindex(self, model_ref):
        for elem in self.load(model_ref).get("elements", []):
            for face in elem.get("faces", {}).values():
                if "tintindex" in face:
                    return True
        return False


def iter_variants(blockstate):
    """Yield (state_string, model_ref) pairs, normalizing 'variants' and 'multipart' schemas.

    Multipart parts (fences/walls/panes/redstone) have no single state string that matters to
    Dynmap - the existing Java renderer classes compute shape from world neighbors, not from a
    stored per-part texture choice - so parts are yielded under one shared synthetic key.
    """
    if "variants" in blockstate:
        for state_str, val in blockstate["variants"].items():
            entry = val[0] if isinstance(val, list) else val
            model = entry.get("model")
            if model:
                yield (state_str, model)
    elif "multipart" in blockstate:
        for part in blockstate["multipart"]:
            apply = part.get("apply", {})
            entry = apply[0] if isinstance(apply, list) else apply
            model = entry.get("model")
            if model:
                yield ("", model)


def normalize_when(when):
    """A multipart 'when' clause into a list of flat {property: value} conditions (one per
    OR-alternative, each already AND-flattened). No 'when' at all means "always applies"."""
    if when is None:
        return [{}]
    if "OR" in when:
        return [cond for sub in when["OR"] for cond in normalize_when(sub)]
    if "AND" in when:
        merged = {}
        for sub in when["AND"]:
            merged.update(sub)
        return [merged]
    return [dict(when)]


class BlockInfo:
    """Everything derived from a block's blockstate+model JSON, needed for signature/cloning."""

    def __init__(self, name, blockstate, cache):
        self.name = name
        # variant_roles: state_string -> {(parent, role): leaf_texture}
        self.variant_roles = {}
        self.parents = set()
        self.schema = "multipart" if "multipart" in blockstate else ("variants" if "variants" in blockstate else "none")
        self.is_leaves = False
        for state_str, model in iter_variants(blockstate):
            parent = cache.immediate_parent(model)
            if parent is None:
                continue
            self.parents.add(parent)
            roles = self.variant_roles.setdefault(state_str, {})
            for role, tex in cache.own_textures(model).items():
                roles[(parent, role)] = tex
            if parent == "block/leaves" or cache.has_tintindex(model):
                self.is_leaves = True

        # Most multipart blocks (fences/walls/panes) never filter texture_1.txt lines by state -
        # their Java renderer looks at world neighbors instead, so variant_roles above (merged,
        # unconditional) is all cloning ever needs. A few (shelf) DO carry real per-state texture
        # differences though, keyed by the block's own persisted properties (powered/facing/...),
        # not by world context - keep each part's condition so roles_for_state() can reconstruct
        # what's active for one specific real state combination.
        self.multipart_conditions = []
        if self.schema == "multipart":
            for part in blockstate["multipart"]:
                apply = part.get("apply", {})
                entry = apply[0] if isinstance(apply, list) else apply
                model = entry.get("model")
                parent = cache.immediate_parent(model) if model else None
                if parent is None:
                    continue
                roles = {(parent, role): tex for role, tex in cache.own_textures(model).items()}
                for cond in normalize_when(part.get("when")):
                    self.multipart_conditions.append((cond, roles))

    def roles_for_state(self, state_str):
        """Merged roles of every multipart condition satisfied by one full state combination
        (e.g. 'powered=true,facing=north,side_chain=unconnected') - a condition only naming a
        subset of properties (e.g. just 'facing') matches any state agreeing on that subset."""
        full = dict(p.split("=", 1) for p in state_str.split(",") if "=" in p)
        merged = {}
        for cond, roles in self.multipart_conditions:
            if all(full.get(k) == v for k, v in cond.items()):
                merged.update(roles)
        return merged

    @property
    def signature(self):
        # Parents alone are too coarse: e.g. chiseled_sandstone (stateless) and deepslate (axis
        # x/y/z via rotation, no separate horizontal model) are both plain 'cube_column' but are
        # not interchangeable templates - fold in the schema and the state property *names*
        # (not values, which legitimately differ block to block) to tell them apart.
        prop_names = frozenset(
            name for state_str in self.variant_roles for name in re.findall(r"([a-z_]+)=", state_str)
        )
        return (self.schema, frozenset(self.parents), prop_names)

    def merged_roles(self):
        merged = {}
        for roles in self.variant_roles.values():
            merged.update(roles)
        return merged


def load_all_blocks(zf, cache):
    blocks = {}
    for info in zf.infolist():
        if info.filename.startswith("assets/minecraft/blockstates/") and info.filename.endswith(".json"):
            name = info.filename.rsplit("/", 1)[-1][:-5]
            try:
                blockstate = json.loads(zf.read(info.filename))
            except (json.JSONDecodeError, KeyError):
                continue
            blocks[name] = BlockInfo(name, blockstate, cache)
    return blocks


def strip_line_guard(line):
    """Strip a leading '[version-range]' guard, if present, returning the rest of the line."""
    if line.startswith("["):
        end = line.find("]")
        if end >= 0:
            return line[end + 1:]
    return line


def parse_tokens(line):
    return [t for t in line.split(",")]


def get_id_token_values(tokens):
    """A single directive line can carry several 'id=' tokens (e.g. copper_block/waxed_copper_block
    sharing one 'block:' line, or several classes sharing one 'customblock:' line)."""
    values = []
    for t in tokens:
        if t.startswith("id="):
            v = t[3:]
            if v and v[0] in "%&":
                v = v[1:]
            values.append(v)
    return values


# Hand-authored geometry directives in models_1.txt that (unlike customblock:) don't delegate to
# a Java renderer class: their box/patch coordinates are purely geometric (no texture name inside),
# so cloning them for a new block of the same family is a plain 'id=' substitution - no per-role
# texture mapping needed, since the actual per-material texture is applied separately by the
# corresponding texture_1.txt 'block:' line via its patchN=idx:texture tokens.
GEOMETRY_DIRECTIVES = ("modellist", "boxblock", "patchblock", "patchrotate")


def scan_existing(texture_1_path, models_1_path):
    """Returns (covered_block_lines, existing_texture_ids, covered_by_customblock, covered_geometry_lines)."""
    covered_block_lines = {}  # block name -> list[str] raw 'block:' lines (guard stripped)
    existing_texture_ids = set()
    covered_by_customblock = {}  # block name -> class
    covered_geometry_lines = {}  # block name -> list[str] raw '<directive>:...' lines

    for raw in texture_1_path.read_text(encoding="utf-8").splitlines():
        line = strip_line_guard(raw.strip())
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if ":" not in line:
            continue
        directive, rest = line.split(":", 1)
        if directive in ("texture", "texturefile"):
            for t in parse_tokens(rest):
                if t.startswith("id="):
                    existing_texture_ids.add(t[3:])
        elif directive == "block":
            for block_id in get_id_token_values(parse_tokens(rest)):
                covered_block_lines.setdefault(block_id, []).append(rest)
        elif directive == "copyblock":
            for block_id in get_id_token_values(parse_tokens(rest)):
                covered_block_lines.setdefault(block_id, [])

    for raw in models_1_path.read_text(encoding="utf-8").splitlines():
        line = strip_line_guard(raw.strip())
        if not line or line.startswith("#") or ":" not in line:
            continue
        directive, rest = line.split(":", 1)
        tokens = parse_tokens(rest)
        if directive == "customblock":
            cls = next((t[6:] for t in tokens if t.startswith("class=")), None)
            if cls:
                for t in tokens:
                    if t.startswith("id="):
                        covered_by_customblock[t[3:]] = cls
        elif directive in GEOMETRY_DIRECTIVES:
            for block_id in get_id_token_values(tokens):
                covered_geometry_lines.setdefault(block_id, []).append(f"{directive}:{rest}")

    return covered_block_lines, existing_texture_ids, covered_by_customblock, covered_geometry_lines


def find_sibling_candidates(new_block, all_blocks, covered_block_lines):
    """All already-covered blocks sharing the same model-parent signature.

    Several unrelated blocks can share a signature (e.g. oak_log AND oak_wood are both
    cube_column) while mapping textures differently (distinct top/side vs. bark-everywhere) -
    so callers must be able to try more than one candidate before giving up.
    """
    if not new_block.parents:
        return []
    sig = new_block.signature
    return [c for name in covered_block_lines if (c := all_blocks.get(name)) is not None and c.signature == sig]


def roles_for(block, state_str):
    if not state_str:
        # Stateless / customblock-family line (fences, stairs, doors...): use the merged
        # roles across every variant/part, since those all resolve to the same single texture
        # in every known vanilla case that uses an unconditioned line.
        return block.merged_roles()
    if block.schema == "multipart":
        return block.roles_for_state(state_str)
    return block.variant_roles.get(state_str) or block.merged_roles()


def build_substitution(sibling, new_block, state_str):
    """Old-leaf -> new-leaf map for the roles active in a specific sibling variant/state.

    Returns None if roles are inconsistent (conflicting mapping) - caller should skip
    rather than guess.
    """
    sibling_roles = roles_for(sibling, state_str)
    new_roles = roles_for(new_block, state_str)

    mapping = {}
    for key, old_leaf in sibling_roles.items():
        if key not in new_roles:
            continue
        new_leaf = new_roles[key]
        if old_leaf in mapping and mapping[old_leaf] != new_leaf:
            return None  # conflicting substitution - don't guess
        mapping[old_leaf] = new_leaf
    return mapping


def clone_block_lines(sibling, new_block, covered_lines_for_sibling, warnings):
    """Produce new 'block:' line bodies (without the 'block:' prefix) for new_block.

    A line can carry several OR'd 'data=' and/or 'state=' selector tokens (e.g. a slab line
    matching both 'type:top' and 'type:bottom') - all of them must be resolved and converted,
    not just the first, or the clone would silently keep a fragile registration-order 'data=N'
    token that may not mean the same thing for the new block.
    """
    out_lines = []
    new_leaves = set()
    for raw_line in covered_lines_for_sibling:
        tokens = parse_tokens(raw_line)
        selectors = {}  # token index -> resolved state string ("" for a stateless line)
        bad = False
        for i, t in enumerate(tokens):
            if t.startswith("data="):
                try:
                    n = int(t[5:])
                    selectors[i] = list(sibling.variant_roles.keys())[n]
                except (ValueError, IndexError):
                    warnings.append(f"{new_block.name}: could not resolve '{t}' from {sibling.name}, skipping line")
                    bad = True
                    break
            elif t.startswith("state="):
                selectors[i] = t[6:].replace("/", ",").replace(":", "=")
        if bad:
            continue
        state_strs = list(selectors.values()) or [""]  # stateless line (fences/stairs/doors/...)

        combined_mapping = {}
        conflict = missing_state = False
        for state_str in state_strs:
            # variant_roles is keyed by the exact state string only for the 'variants' schema
            # (multipart blocks are matched condition-by-condition in roles_for_state instead,
            # where an empty result is a normal, harmless "no extra part applies here").
            if state_str and new_block.schema == "variants" and new_block.variant_roles.get(state_str) is None:
                warnings.append(f"{new_block.name}: has no state '{state_str}' like sibling {sibling.name}, skipping that line")
                missing_state = True
                break
            mapping = build_substitution(sibling, new_block, state_str)
            if mapping is None:
                conflict = True
                break
            for old_leaf, new_leaf in mapping.items():
                if old_leaf in combined_mapping and combined_mapping[old_leaf] != new_leaf:
                    conflict = True
                    break
                combined_mapping[old_leaf] = new_leaf
            if conflict:
                break
        if missing_state:
            continue
        if conflict:
            warnings.append(f"{new_block.name}: conflicting texture roles vs {sibling.name}, skipping a line")
            continue

        new_tokens = []
        id_emitted = False
        for i, t in enumerate(tokens):
            if t.startswith("id="):
                # A sibling line may carry several 'id=' tokens (e.g. copper_block/waxed_copper_block
                # sharing one line) - the clone is for exactly one new block, so keep only the first.
                if not id_emitted:
                    new_tokens.append(f"id={new_block.name}")
                    id_emitted = True
                continue
            if i in selectors:
                dynmap_state = state_str_to_dynmap(selectors[i])
                if dynmap_state:
                    new_tokens.append(f"state={dynmap_state}")
                continue
            m = FACE_TEXTURE_RE.match(t)
            if m:
                key, idx, old_leaf = m.groups()
                new_leaf = combined_mapping.get(old_leaf, old_leaf)
                if old_leaf not in combined_mapping:
                    warnings.append(f"{new_block.name}: texture '{old_leaf}' in cloned line has no known substitute, kept as-is")
                new_tokens.append(f"{key}={idx}:{new_leaf}")
                new_leaves.add(new_leaf)
                continue
            m = BLOCKCOLOR_RE.match(t)
            if m:
                old_leaf = m.group(1)
                new_leaf = combined_mapping.get(old_leaf, old_leaf)
                new_tokens.append(f"blockcolor={new_leaf}")
                new_leaves.add(new_leaf)
                continue
            new_tokens.append(t)
        out_lines.append(",".join(new_tokens))
    return out_lines, new_leaves


def clone_geometry_lines(new_name, geometry_lines):
    """Clone models_1.txt geometry lines (modellist/boxblock/patchblock/patchrotate) for a new
    block: pure 'id=' substitution, since their box/patch coordinates carry no texture name."""
    out = []
    for raw_line in geometry_lines:
        directive, rest = raw_line.split(":", 1)
        new_tokens = []
        id_emitted = False
        for t in parse_tokens(rest):
            if t.startswith("id="):
                if not id_emitted:
                    new_tokens.append(f"id={new_name}")
                    id_emitted = True
                continue
            new_tokens.append(t)
        out.append(f"{directive}:{','.join(new_tokens)}")
    return out


def build_simple_leaves_line(new_block):
    tone = LEAF_TONE_OVERRIDES.get(new_block.name, FOLIAGE_TINT_PREFIX)
    roles = new_block.merged_roles()
    tex = next(iter(roles.values()), new_block.name)
    return [f"id={new_block.name},allfaces={tone}:{tex},stdrot=true,transparency=LEAVES"], {tex}


def backup_file(path, backup_path):
    """Copy path -> backup_path (overwriting any earlier backup). No-op if path doesn't exist
    yet (nothing to protect on a from-scratch run)."""
    if path.exists():
        shutil.copy2(path, backup_path)


def restore_backup(path, backup_path):
    """Delete path and move backup_path back into its place. Returns True if a backup existed
    and was restored, False if there was no backup to restore from."""
    if not backup_path.exists():
        return False
    if path.exists():
        path.unlink()
    shutil.move(str(backup_path), str(path))
    return True


def extract_texture_png(zf, leaf, dest_dir, dry_run, copied, missing):
    dest = dest_dir / f"{leaf}.png"
    if dest.exists():
        return
    src = f"assets/minecraft/textures/block/{leaf}.png"
    try:
        data = zf.read(src)
    except KeyError:
        missing.append(leaf)
        return
    copied.append(leaf)
    if not dry_run:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        mcmeta_src = src + ".mcmeta"
        try:
            dest.with_suffix(".png.mcmeta").write_bytes(zf.read(mcmeta_src))
        except KeyError:
            pass


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--client-jar", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", type=Path)
    ap.add_argument("--no-backup", action="store_true",
                     help="Don't save a .bak copy of texture_1.txt/models_1.txt before writing (on by default)")
    ap.add_argument("--undo", action="store_true",
                     help="Restore texture_1.txt/models_1.txt from the .bak copy saved by the last real run, then exit")
    args = ap.parse_args()

    if args.undo:
        restored = []
        for path, backup_path in ((TEXTURE_1, TEXTURE_1_BACKUP), (MODELS_1, MODELS_1_BACKUP)):
            if restore_backup(path, backup_path):
                restored.append(path.name)
                print(f"Restored {path.name} from {backup_path.name}")
            else:
                print(f"No backup found for {path.name} - left as-is")
        if not restored:
            print("Nothing to undo.")
            return 1
        return 0

    if args.client_jar is None:
        ap.error("--client-jar is required unless --undo is given")

    with zipfile.ZipFile(args.client_jar) as zf:
        try:
            mc_version = json.loads(zf.read("version.json")).get("id", "unknown")
        except KeyError:
            mc_version = "unknown"

        cache = ModelCache(zf)
        all_blocks = load_all_blocks(zf, cache)
        covered_block_lines, existing_texture_ids, covered_by_customblock, covered_geometry_lines = scan_existing(TEXTURE_1, MODELS_1)

        added_simple = []
        added_cloned = []
        manual_review = []
        warnings = []
        new_texture_lines = []
        new_block_lines = []
        new_models_lines = []
        copied_pngs = []
        missing_pngs = []

        for name in sorted(all_blocks):
            if name in covered_block_lines or name in covered_by_customblock:
                continue
            new_block = all_blocks[name]
            if not new_block.parents:
                manual_review.append((name, "no resolvable model parent"))
                continue

            if new_block.is_leaves:
                lines, leaves = build_simple_leaves_line(new_block)
                added_simple.append(name)
            else:
                candidates = find_sibling_candidates(new_block, all_blocks, covered_block_lines)
                # Several unrelated blocks can share a signature (oak_log vs. oak_wood, both
                # cube_column) - prefer richer templates (more distinct textures) first, since a
                # bark-everywhere sibling can't teach us a real top/side split.
                candidates.sort(key=lambda c: len(set(c.merged_roles().values())), reverse=True)

                best_sibling = best_lines = best_leaves = None
                best_warnings = []
                for candidate in candidates:
                    sibling_lines = covered_block_lines.get(candidate.name, [])
                    if not sibling_lines:
                        continue
                    attempt_warnings = []
                    lines, leaves = clone_block_lines(candidate, new_block, sibling_lines, attempt_warnings)
                    if len(lines) == len(sibling_lines):
                        best_sibling, best_lines, best_leaves, best_warnings = candidate, lines, leaves, attempt_warnings
                        break  # full match - no need to consider other candidates
                    if lines and (best_lines is None or len(lines) > len(best_lines)):
                        best_sibling, best_lines, best_leaves, best_warnings = candidate, lines, leaves, attempt_warnings

                if best_sibling is None:
                    manual_review.append((name, f"no sibling found, parents={sorted(new_block.parents)}"))
                    continue
                sibling, lines, leaves = best_sibling, best_lines, best_leaves
                warnings.extend(best_warnings)
                added_cloned.append((name, sibling.name))
                cls = covered_by_customblock.get(sibling.name)
                if cls:
                    new_models_lines.append(f"customblock:id={name},class={cls}")
                sibling_geometry = covered_geometry_lines.get(sibling.name)
                if sibling_geometry:
                    new_models_lines.extend(clone_geometry_lines(name, sibling_geometry))

            for line in lines:
                new_block_lines.append(f"block:{line}")
            for leaf in sorted(leaves):
                if leaf not in existing_texture_ids:
                    new_texture_lines.append(f"texture:id={leaf}")
                    existing_texture_ids.add(leaf)
                extract_texture_png(zf, leaf, BLOCK_TEXTURES_DIR, args.dry_run, copied_pngs, missing_pngs)

        if not args.dry_run and (new_texture_lines or new_block_lines):
            if not args.no_backup:
                backup_file(TEXTURE_1, TEXTURE_1_BACKUP)
                print(f"Backed up {TEXTURE_1.name} -> {TEXTURE_1_BACKUP.name} (undo with --undo)")
            header = f"\n# Added for MC {mc_version} by tools/texture_gen/generate_texture_1.py\n"
            with TEXTURE_1.open("a", encoding="utf-8") as f:
                f.write(header)
                for line in new_texture_lines:
                    f.write(line + "\n")
                for line in new_block_lines:
                    f.write(line + "\n")

        if not args.dry_run and new_models_lines:
            if not args.no_backup:
                backup_file(MODELS_1, MODELS_1_BACKUP)
                print(f"Backed up {MODELS_1.name} -> {MODELS_1_BACKUP.name} (undo with --undo)")
            header = f"\n# Added for MC {mc_version} by tools/texture_gen/generate_texture_1.py\n"
            with MODELS_1.open("a", encoding="utf-8") as f:
                f.write(header)
                for line in new_models_lines:
                    f.write(line + "\n")

        report = render_report(mc_version, args.dry_run, added_simple, added_cloned, manual_review, warnings, copied_pngs, missing_pngs)
        print(report)
        if args.report:
            args.report.write_text(report, encoding="utf-8")


def render_report(mc_version, dry_run, added_simple, added_cloned, manual_review, warnings, copied_pngs, missing_pngs):
    lines = [f"# texture_1.txt generation report - MC {mc_version}{' (dry run)' if dry_run else ''}", ""]
    lines.append(f"## Simple blocks added ({len(added_simple)})")
    lines.extend(f"- {n}" for n in added_simple)
    lines.append("")
    lines.append(f"## Cloned from an existing sibling ({len(added_cloned)})")
    lines.extend(f"- {n} (from {src})" for n, src in added_cloned)
    lines.append("")
    lines.append(f"## Needs manual review ({len(manual_review)})")
    lines.extend(f"- {n}: {reason}" for n, reason in manual_review)
    lines.append("")
    lines.append(f"## PNGs copied ({len(copied_pngs)})")
    lines.extend(f"- {n}.png" for n in copied_pngs)
    if missing_pngs:
        lines.append("")
        lines.append(f"## PNGs referenced but not found in jar ({len(missing_pngs)})")
        lines.extend(f"- {n}.png" for n in missing_pngs)
    if warnings:
        lines.append("")
        lines.append(f"## Warnings ({len(warnings)})")
        lines.extend(f"- {w}" for w in warnings)
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())

# ,fbiengàreinguo pk u inuhzr rutzrg