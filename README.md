# TW1 Minimap Tool

View, replace and create the minimap tiles of **Two Worlds 1** (2007) — the
parchment map shown on the minimap and the map screen.

The game never reads the BMP the editor saves next to a level. It uses
`Levels\MipMaps\Map_<level>@0.dds` … `@3.dds` (DXT1, 512/256/128/64 px)
from `Levels.wd`, matched only by file name. This tool builds the whole
world map from those tiles (surface A01–I12 and the underworld `_1` tiles),
lets you click a tile, insert any PNG/JPG/BMP/DDS of 512 px or more, writes
the four DXT1 levels with verified sizes and packs them as a mod archive.
Retail archives are never touched.

## Features

* World map from the 512 px tiles, two layers (surface / underworld), zoom
  with the mouse wheel, right-drag to pan
* Insert an image for any tile; larger images are scaled, non-square ones
  centre-cropped; every replaced state is backed up first (`backup\`)
* New tiles outside the retail grid (Y/Z and J/K columns, rows −1…14),
  e.g. for new levels `Map_C13.lnd → C13`
* Export a tile or a whole layer as PNG/JPG/DDS for editing elsewhere
* *Apply to game*: packs the output folder as `Mods\Minimap.wd` (via
  buglord's `wdio`) and enables it in the registry
* Step-by-step guided tour on first start, English/German (follows the
  Windows display language)

## Run

* **Exe:** download `TW1 Minimap Tool.exe` from the releases, no install.
  Data lives in `%LOCALAPPDATA%\TW1MinimapTool\`.
* **Script:** Python 3.13 with Pillow 12 (`pip install pillow`), then
  `python minimap_tool.py`. Data lives next to the script.

The game folder is read from `HKLM\SOFTWARE\WOW6432Node\Reality Pump\TwoWorlds\FileSystem\DataPath`.

## Build the exe

`build_minimap_exe.bat` (PyInstaller, one file, no console). Result in
`dist\`.

## Naming

Rows 1–9 carry a leading zero (`E06`), 10–12 don't (`E10`); underworld
tiles end in `_1` (`F01_1`). The search box accepts any spelling.
Sizes per level are fixed: 131200 / 32896 / 8320 / 2176 bytes.

## Credits

`wdio.py` — WD archive packer by [buglord](https://github.com/buglord)
(CC0). Everything else CC0 as well, see `LICENSE`.

Links: [Alchemy Fox](https://alchemy-fox.de/) ·
[TW1 community server](https://twmp.alchemy-fox.de/)
