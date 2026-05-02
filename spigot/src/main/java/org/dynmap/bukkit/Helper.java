package org.dynmap.bukkit;

import java.lang.reflect.Constructor;

import org.bukkit.Bukkit;
import org.dynmap.Log;
import org.dynmap.bukkit.helper.BukkitVersionHelper;

public class Helper {

	private static BukkitVersionHelper loadVersionHelper(String classname) {
		try {
			Class<?> c = Class.forName(classname);
			Constructor<?> cons = c.getConstructor();
			return (BukkitVersionHelper) cons.newInstance();
		} catch (Exception x) {
			Log.severe("Error loading " + classname, x);
			return null;
		}
	}
    public static final BukkitVersionHelper getHelper() {
        if (BukkitVersionHelper.helper == null) {
        	String v = Bukkit.getServer().getVersion();
            Log.info("version=" + v);
            if (v.contains("MCPC")) {
                Log.severe("*********************************************************************************");
                Log.severe("* MCPC-Plus is no longer supported via the Bukkit version of Dynmap.            *");
                Log.severe("* Install the appropriate Forge version of Dynmap.                              *");
                Log.severe("* Add the DynmapCBBridge plugin to enable support for Dynmap-compatible plugins *");
                Log.severe("*********************************************************************************");
            }
            else if(v.contains("BukkitForge")) {
                Log.severe("*********************************************************************************");
                Log.severe("* BukkitForge is not supported via the Bukkit version of Dynmap.                *");
                Log.severe("* Install the appropriate Forge version of Dynmap.                              *");
                Log.severe("* Add the DynmapCBBridge plugin to enable support for Dynmap-compatible plugins *");
                Log.severe("*********************************************************************************");
            }
            else if(Bukkit.getServer().getClass().getName().contains("GlowServer")) {
                Log.info("Loading Glowstone support");
                BukkitVersionHelper.helper = loadVersionHelper("org.dynmap.bukkit.helper.BukkitVersionHelperGlowstone");
            }
            else if (v.contains("(MC: 1.21.6") || v.contains("(MC: 1.21.7") || v.contains("(MC: 1.21.8")) {
	            BukkitVersionHelper.helper = loadVersionHelper("org.dynmap.bukkit.helper.v121_6.BukkitVersionHelperSpigot121_6");
            }
            else if (v.contains("(MC: 1.21.9)") || v.contains("(MC: 1.21.10)") || v.contains("(MC: 1.21.9 Unobfuscated)") || v.contains("(MC: 1.21.10 Unobfuscated)")) {
	            BukkitVersionHelper.helper = loadVersionHelper("org.dynmap.bukkit.helper.v121_10.BukkitVersionHelperSpigot121_10");
            }
            else if (v.contains("(MC: 1.21.11)") || v.contains("(MC: 1.21.11 Unobfuscated)")) {
	            BukkitVersionHelper.helper = loadVersionHelper("org.dynmap.bukkit.helper.v121_11.BukkitVersionHelperSpigot121_11");
            }
            else if (v.contains("(MC: 26.1.2)") || v.contains("(MC: 26.1.1)") || v.contains("(MC: 26.1)")) {
                BukkitVersionHelper.helper = loadVersionHelper("org.dynmap.bukkit.helper.v26_1_2.BukkitVersionHelperSpigot26_1_2");
            }
            else {
            	BukkitVersionHelper.helper = loadVersionHelper("org.dynmap.bukkit.helper.BukkitVersionHelperCB");
            }
        }
        return BukkitVersionHelper.helper;
    }

}
