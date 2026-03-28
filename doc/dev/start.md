- [How to start the development on the Dynmap plugin project ?](#how-to-start-the-development-on-the-dynmap-plugin-project-)
  - [Compiling the project](#compiling-the-project)

# How to start the development on the Dynmap plugin project ? 

## Compiling the project

The project must be compiled and packaged in a jar file using the command `./gradlew :<project>:<goal>`

With project being
- `bukkit-helper...`
- `spigot`
- `fabric`
- `forge`

And the goal being
- `shadowJar` (A custom goal to generate a jar package containing necessary dependencies)
- `compileJava`
- `clean`
- ...

> In case of generating a jar, the file will be available at `/target/`