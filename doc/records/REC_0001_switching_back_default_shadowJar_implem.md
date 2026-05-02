# Switching back to the default implementation of gradle ShadowJar plugin

02/05/2026
Removing the `io.github.gooler.shadow` plugin and switch back to the official shadowJar plugin (`com.gradleup.shadow`)

## Context

After taking back the dynmap project, one of the first thing that I implemented was the 26.1 compatibility. 
In the vision of upgrading the dynmap codebase, I choosed to switch to Java version 25. The old plugin was not updated anymore. Switching back to `com.gradleup.shadow` was mandatory in this context.

> I don't know if updating java version was mandatory

By doing so, I needed to update the import list because the syntax `include(dependency("commons-code::"))` using the double `:` seems to create bugs : The decompiled JAR didn't contain the included dependency.

## Other options

I could have stayed in Java 17 version. Why updating ? I want to upgrade the codebase to progressivly bring back codebase to the last versions.