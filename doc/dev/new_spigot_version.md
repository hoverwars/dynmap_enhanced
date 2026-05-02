# Develop a new spigot version 

This documentation gives the keys to implement a new spigot version for this project, step by step.

## Get a new bukkit-helper version

Firstly, take the last bukkit-helper version and copy it to a new folder called `bukkit-helper-<the new version>`. You will need to update

- The names of classes `BukkitVersionHelperSpigot<Version>.java` and `MapChunkCache<Version.java` inside the new folder
- The `build.gradle` file inside the new folder. 
  - Update the spigot and spigot-api version to the desired version.
  - Update the description, on top of the file.

## Register the new bukkit-helper version

After creating this new gradle sub project, you should register it inside the root project.

- Open `settings.gradle`.
  - Add the appropriate include section: `include :bukkit-helper-<version>` 
  - Add the appropriate project section: `project(':bukkit-helper-<version>').projectDir = "$rootDir/<path_to_the_project>" as File`
- Open `build.gradle` of the spigot project. Copy the project include from the last bukkit version. 
- Update the `Helper.java` class inside the Spigot project. Follow the existing structure to ensure the right version is loaded. You can find the right version naming by starting your minecraft server.

## Implement the bukkit-helper version

Make the code changes necessary to ensure this new version is running with the current version of NMS. 