- [Ajouter un nouveau bloc pour qu'il soit géré par le plugin dynmap](#ajouter-un-nouveau-bloc-pour-quil-soit-géré-par-le-plugin-dynmap)
  - [Récupérer les textures concernées](#récupérer-les-textures-concernées)
  - [Modifier les fichiers de texture dans le code du projet Dynmap.](#modifier-les-fichiers-de-texture-dans-le-code-du-projet-dynmap)
  - [Mon nouveau bloc ne correspond à aucun type de bloc existant actuellement sur la dynmap](#mon-nouveau-bloc-ne-correspond-à-aucun-type-de-bloc-existant-actuellement-sur-la-dynmap)

# Ajouter un nouveau bloc pour qu'il soit géré par le plugin dynmap

Cette documentation regroupe les étapes nécessaires pour supporter un nouveau bloc sur le plugin dynmap

## Récupérer les textures concernées

Dans un premier temps, il faut décompresser le contenu du jeu de base, dans la version ciblée pour le développement. dans le dossier décompressé, se rendre dans le dossier `assets/minecraft/textures`. Ce dossier contient toutes les textures nécessaires pour faire fonctionner le jeu. <br>
A partir de ce fichier, récupérer toutes les textures à gérer et les mettre de côté pour la suite

## Modifier les fichiers de texture dans le code du projet Dynmap. 

Tout se passe dans le projet `DynmapCore`. Il faudra modifier les fichiers de ressource de ce projet pour y ajouter les nouvelles textures et modifier les fichiers textuels référençant ces textures.



## Mon nouveau bloc ne correspond à aucun type de bloc existant actuellement sur la dynmap

> A rédiger