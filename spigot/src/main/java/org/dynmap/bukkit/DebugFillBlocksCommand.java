package org.dynmap.bukkit;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

import org.bukkit.Bukkit;
import org.bukkit.Location;
import org.bukkit.World;
import org.bukkit.command.CommandSender;
import org.bukkit.entity.Player;
import org.bukkit.scheduler.BukkitTask;

import org.dynmap.DynmapCore;
import org.dynmap.common.DynmapCommandSender;
import org.dynmap.bukkit.helper.BukkitVersionHelper;
import org.dynmap.renderer.DynmapBlockState;

/**
 * Debug/testing command (Bukkit-only, not routed through DynmapCore.processCommand since it needs
 * raw world-editing access): fills a flat test world with every block state Dynmap knows about
 * (every orientation/variant, including waterlogged, etc.), plus a handful of connector rigs for
 * blocks whose connections (fences, walls, glass panes, iron bars, chains) are derived from
 * neighboring blocks rather than stored as block-state properties. The goal is a one-stop map area
 * to visually confirm Dynmap renders every block correctly.
 *
 * Usage: /dynmap debugblocks [confirm|cancel]
 */
public class DebugFillBlocksCommand {
    private static final long CONFIRM_TIMEOUT_MS = 30_000L;
    private static final int BLOCKS_PER_TICK = 400;
    private static final int SPACING = 2; // grid cells are SPACING blocks apart on X/Z
    private static final int RIG_SPACING = 6; // spacing between connector rigs

    private static class PendingFill {
        final Location origin;
        final long requestedAt = System.currentTimeMillis();
        PendingFill(Location origin) { this.origin = origin; }
        boolean isExpired() { return System.currentTimeMillis() - requestedAt > CONFIRM_TIMEOUT_MS; }
    }

    private static final Map<UUID, PendingFill> pending = new HashMap<UUID, PendingFill>();
    private static volatile boolean running = false;

    public static boolean processCommand(DynmapPlugin plugin, DynmapCore core, CommandSender sender, String[] args) {
        if (!(sender instanceof Player)) {
            sender.sendMessage("This command must be run in-game: it fills the world around your current location.");
            return true;
        }
        Player player = (Player) sender;
        if (!player.hasPermission("dynmap.debug.fillallblocks")) {
            sender.sendMessage("You do not have permission to use this command.");
            return true;
        }
        String sub = (args.length >= 1) ? args[0].toLowerCase() : "";

        if (sub.equals("cancel")) {
            pending.remove(player.getUniqueId());
            sender.sendMessage("Pending debugblocks request cancelled.");
            return true;
        }
        if (running) {
            sender.sendMessage("A debugblocks run is already in progress on this server - wait for it to finish.");
            return true;
        }

        World world = player.getWorld();
        if (!BukkitVersionHelper.helper.isFlatWorld(world)) {
            sender.sendMessage("This command only works on flat (superflat) worlds, since it overwrites a large area of terrain.");
            sender.sendMessage("Teleport to (or create) a disposable superflat test world first.");
            return true;
        }

        List<DynmapBlockState> states = collectPlaceableStates();
        List<String> connectorBases = collectConnectorBaseNames(states);
        int cols = (int) Math.ceil(Math.sqrt(states.size()));
        int rows = (states.size() + cols - 1) / cols;

        if (!sub.equals("confirm")) {
            pending.put(player.getUniqueId(), new PendingFill(player.getLocation().getBlock().getLocation()));
            sender.sendMessage("WARNING: this will place " + states.size() + " block states (every orientation/variant "
                    + "Dynmap knows about) in a " + cols + "x" + rows + " grid (spacing " + SPACING + "), starting at "
                    + "your current location, plus " + connectorBases.size() + " connector rigs for fences/walls/panes/bars.");
            sender.sendMessage("It WILL overwrite any existing blocks in that area. Run /dynmap debugblocks confirm "
                    + "within 30 seconds to proceed, or /dynmap debugblocks cancel to abort.");
            return true;
        }

        PendingFill pf = pending.remove(player.getUniqueId());
        if ((pf == null) || pf.isExpired()) {
            sender.sendMessage("No pending confirmation (or it expired) - run /dynmap debugblocks again first.");
            return true;
        }
        startFill(plugin, core, player, pf.origin, states, connectorBases, cols);
        return true;
    }

    // Block-state properties known to never change a block's rendered appearance (only its game behavior),
    // keyed by block name - deduplicated away so the grid isn't flooded with visually-identical repeats.
    // Deliberately conservative/per-block rather than a blanket property-name blacklist: e.g. "powered" is
    // cosmetically irrelevant for a noteblock but DOES change the texture of a powered rail, so it can't be
    // ignored globally.
    private static final Map<String, Set<String>> COSMETIC_IGNORE_PROPS = new HashMap<String, Set<String>>();
    static {
        COSMETIC_IGNORE_PROPS.put("minecraft:note_block", new HashSet<String>(Arrays.asList("instrument", "note", "powered")));
        COSMETIC_IGNORE_PROPS.put("minecraft:scaffolding", new HashSet<String>(Arrays.asList("distance")));
    }
    // Leaves of any wood type: "distance"/"persistent" only affect decay logic, never the rendered texture.
    private static final Set<String> LEAF_IGNORE_PROPS = new HashSet<String>(Arrays.asList("distance", "persistent"));

    private static List<DynmapBlockState> collectPlaceableStates() {
        List<DynmapBlockState> list = new ArrayList<DynmapBlockState>();
        Set<String> seenCosmeticKeys = new HashSet<String>();
        int max = DynmapBlockState.getGlobalIndexMax();
        for (int i = 0; i < max; i++) {
            DynmapBlockState bs = DynmapBlockState.getStateByGlobalIndex(i);
            if ((bs == null) || bs.isAir()) continue;
            String key = cosmeticDedupKey(bs);
            if ((key != null) && !seenCosmeticKeys.add(key)) continue; // skip: cosmetically identical to one already kept
            list.add(bs);
        }
        return list;
    }

    // Returns a key that's identical for states of the same block that only differ in cosmetically-irrelevant
    // properties (so only the first such state is kept), or null if this block has no such properties defined.
    private static String cosmeticDedupKey(DynmapBlockState bs) {
        Set<String> ignore = COSMETIC_IGNORE_PROPS.get(bs.blockName);
        if ((ignore == null) && bs.blockName.endsWith("_leaves")) {
            ignore = LEAF_IGNORE_PROPS;
        }
        if (ignore == null) return null;
        if (bs.stateName.isEmpty()) return bs.blockName;
        List<String> kept = new ArrayList<String>();
        for (String prop : bs.stateName.split(",")) {
            String attrib = prop.split("=", 2)[0];
            if (!ignore.contains(attrib)) kept.add(prop);
        }
        Collections.sort(kept);
        return bs.blockName + "[" + String.join(",", kept) + "]";
    }

    // Base block names that use neighbor-derived "connected texture" rendering (fences, walls, glass
    // panes, iron bars, chains): their connections aren't stored as block-state properties, so on top
    // of their normal per-state grid entries we also build small connected rigs for them.
    private static List<String> collectConnectorBaseNames(List<DynmapBlockState> states) {
        List<String> names = new ArrayList<String>();
        Set<String> seen = new HashSet<String>();
        for (DynmapBlockState bs : states) {
            String n = bs.blockName;
            if (!seen.add(n)) continue;
            if (n.endsWith("_fence") || n.endsWith("_wall") || n.endsWith("_pane")
                    || n.endsWith("_bars") || n.equals("minecraft:chain")) {
                names.add(n);
            }
        }
        return names;
    }

    private static void startFill(final DynmapPlugin plugin, final DynmapCore core, final Player starter,
                                   final Location origin, final List<DynmapBlockState> states,
                                   final List<String> connectorBases, final int cols) {
        running = true;
        final World world = origin.getWorld();
        final int baseX = origin.getBlockX();
        final int baseY = origin.getBlockY();
        final int baseZ = origin.getBlockZ();
        final int rows = (states.size() + cols - 1) / cols;
        final int[] index = { 0 };
        final int[] placed = { 0 };
        final int[] failed = { 0 };
        final long start = System.currentTimeMillis();

        starter.sendMessage("Starting debugblocks: placing " + states.size() + " block states...");

        final BukkitTask[] taskHolder = new BukkitTask[1];
        Runnable step = new Runnable() {
            public void run() {
                int budget = BLOCKS_PER_TICK;
                while ((budget-- > 0) && (index[0] < states.size())) {
                    int i = index[0]++;
                    DynmapBlockState bs = states.get(i);
                    int col = i % cols;
                    int row = i / cols;
                    int x = baseX + col * SPACING;
                    int z = baseZ + row * SPACING;
                    boolean ok = BukkitVersionHelper.helper.setBlockByStateName(world, x, baseY, z, bs.toString());
                    if (ok) {
                        placed[0]++;
                        // Water (and waterlogged) states will happily spread into open neighbor cells once
                        // the fluid ticks, flooding the whole grid - wall them off with invisible barriers.
                        if (bs.isWaterFilled()) {
                            containLiquid(world, x, baseY, z);
                        }
                    } else {
                        failed[0]++;
                    }
                }
                if (index[0] < states.size()) {
                    return; // more to do next tick
                }
                // Main grid done: place the connector rigs below it
                int rigBaseZ = baseZ + (rows + 2) * SPACING;
                int rigX = baseX;
                for (String base : connectorBases) {
                    placeConnectorRig(world, rigX, baseY, rigBaseZ, base);
                    rigX += RIG_SPACING;
                }
                taskHolder[0].cancel();
                running = false;

                long elapsed = System.currentTimeMillis() - start;
                int gridMaxX = baseX + (cols - 1) * SPACING;
                int rigMaxX = rigX + 1; // rigX already advanced one RIG_SPACING past the last rig placed
                int maxX = Math.max(gridMaxX, rigMaxX);
                int maxZ = rigBaseZ + 2;
                String wname = world.getName();
                starter.sendMessage("Done: placed " + placed[0] + " block states (" + failed[0] + " skipped) in "
                        + (elapsed / 1000.0) + "s. Area: (" + baseX + "," + baseZ + ") to (" + maxX + "," + maxZ
                        + ") in world '" + wname + "'.");

                int cx = (baseX + maxX) / 2;
                int cz = (baseZ + maxZ) / 2;
                int radius = Math.max(maxX - baseX, maxZ - baseZ) / 2 + 16;
                DynmapCommandSender dsender = plugin.new BukkitPlayer(starter);
                core.processCommand(dsender, "dynmap", "dynmap", new String[] {
                        "radiusrender", wname, String.valueOf(cx), String.valueOf(cz), String.valueOf(radius) });
                starter.sendMessage("Triggered a radius render to update the map (requires dynmap.radiusrender permission).");
            }
        };
        taskHolder[0] = plugin.getServer().getScheduler().runTaskTimer(plugin, step, 1L, 1L);
    }

    // Builds a plus/cross shape (center + 4 cardinal neighbors) so every connection direction renders.
    private static void placeConnectorRig(World world, int cx, int y, int cz, String stateName) {
        int[][] offsets = { { 0, 0 }, { 1, 0 }, { -1, 0 }, { 0, 1 }, { 0, -1 } };
        for (int[] off : offsets) {
            BukkitVersionHelper.helper.setBlockByStateName(world, cx + off[0], y, cz + off[1], stateName);
        }
    }

    // Surrounds a water/waterlogged cell with invisible barriers on its 4 cardinal sides, one block out
    // (well within the SPACING gap before the next grid cell), so its fluid has nowhere to spread into.
    private static void containLiquid(World world, int x, int y, int z) {
        BukkitVersionHelper.helper.setBlockByStateName(world, x + 1, y, z, "minecraft:barrier");
        BukkitVersionHelper.helper.setBlockByStateName(world, x - 1, y, z, "minecraft:barrier");
        BukkitVersionHelper.helper.setBlockByStateName(world, x, y, z + 1, "minecraft:barrier");
        BukkitVersionHelper.helper.setBlockByStateName(world, x, y, z - 1, "minecraft:barrier");
    }
}
