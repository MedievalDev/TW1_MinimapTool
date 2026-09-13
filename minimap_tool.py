"""TW1 Minimap Tool - die Kartenkacheln von Two Worlds 1 ansehen und tauschen.

Das Spiel zeigt als Minimap und auf der Kartenseite nicht die Editor-BMP,
sondern Levels\\MipMaps\\Map_<Zelle>@0..3.dds aus Levels.wd: handgemaltes
Pergament, DXT1, 512/256/128/64 px, zugeordnet allein ueber den Namen.
Die 108 Aussenzellen (Spalten A-I, Reihen 1-12) passen nahtlos zur Weltkarte
zusammen (gemessen 13.09.2026 an E06..G07); die Innenzellen tragen das
Suffix _1 und bilden die zweite Ebene (Untergrund).

Was das Werkzeug tut:
  * baut die Weltkarte aus den 512er-Kacheln, je Ebene, anklickbar
  * legt fuer eine Zelle ein neues Bild ein (PNG/JPG/BMP/DDS, mind. 512 px,
    groesser wird skaliert, nicht quadratisch wird mittig beschnitten)
  * schreibt die vier DXT1-Stufen mit festen Groessen (131200/32896/8320/2176 B)
    in den Ausgabeordner (Standard: QuestForge\\minimap - von dort packt
    build_campaign.py sie in die Kampagne) oder als eigenes Mod-Archiv .wd
  * exportiert eine Kachel oder die ganze Ebene als PNG/JPG/DDS zum Bearbeiten
  * legt neue Kacheln an, auch ausserhalb des Retail-Rasters (C13, J9, F05_1)

Namensregel (Retail): Reihen 1-9 mit fuehrender Null (E06), 10-12 ohne (E10);
Untergrund mit _1 (F01_1). Die Suche nimmt jede Schreibweise (e6, E06, f1_1).

Start:  py -3.13 minimap_tool.py   (braucht Pillow mit DDS/DXT1 - 12.x)
"""

import io
import os
import webbrowser
import re
import sys
import zlib
import struct

import winreg

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from PIL import Image, ImageTk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# Als Exe (PyInstaller, eine Datei): Ressourcen liegen im entpackten Bundle,
# Daten (Ausgabeordner, Sicherungen, Einstellungen) unter %LOCALAPPDATA%.
FROZEN = bool(getattr(sys, 'frozen', False))
RES = getattr(sys, '_MEIPASS', HERE)
DATEN = os.path.join(os.environ.get('LOCALAPPDATA', HERE), 'TW1MinimapTool') if FROZEN else HERE
import wd_metadaten  # noqa: E402


def _spielpfad():
    """Spielordner: DataPath aus der Registry, sonst der in wd_metadaten eingetragene."""
    kand = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r'SOFTWARE\WOW6432Node\Reality Pump\TwoWorlds\FileSystem') as k:
            kand.append(winreg.QueryValueEx(k, 'DataPath')[0])
    except OSError:
        pass
    kand.append(wd_metadaten.SPIEL)
    for pf in kand:
        if pf and os.path.exists(os.path.join(pf, 'WDFiles', 'Levels.wd')):
            return pf
    return kand[-1]


SPIEL = _spielpfad()
WDFILES = os.path.join(SPIEL, 'WDFiles')
wd_metadaten.SPIEL, wd_metadaten.WDFILES = SPIEL, WDFILES
wd_metadaten.vorlage.__defaults__ = (WDFILES,)     # Default wurde beim def gebunden
import theme  # noqa: E402
from theme import (BG, PANEL, FIELD, CANVAS_BG, LINE, SEL, INK, MUT, DIM, GOLD,  # noqa: E402
                   GOLD_HI, OK, ERR, FONT, FONT_BOLD, FONT_SMALL, FONT_MENU, FONT_BRAND,
                   PLAYER_COLOR, HI_SEL, HI_MARK, HI_MARK_2)

# Farben fuer Kachelzustaende (aus den Datenfarben des Themes)
FARBE_NEU = '#e0a050'          # eingelegt, ungespeichert
FARBE_MOD = PLAYER_COLOR       # im Ausgabeordner
FARBE_TEXT_AUF_GOLD = '#17130b'
# Auswahl und Tour-Ziel muessen auf dem Pergament sofort ins Auge fallen:
# Gold geht dort unter, deshalb kraeftiges Rot fuer die Auswahl und
# blinkendes Gruen/Gelb fuer alles, was die Einfuehrung markiert.
FARBE_AUSWAHL = HI_SEL
FARBE_TOUR = HI_MARK
FARBE_TOUR_2 = HI_MARK_2

VERSION = '1.0'
# Links im Hilfe-Menue und im Ueber-Dialog (PY_TOOL_DESIGN.md, Abschnitt 7).
# Repo und Guide-Seite fuer dieses Tool sind noch anzulegen.
GITHUB_URL = 'https://github.com/MedievalDev/TW1_MinimapTool'
SITE_URL = 'https://alchemy-fox.de/'
GUIDE_URL = 'https://alchemy-fox.de/game/TW1_MinimapTool/'
COMMUNITY_URL = 'https://twmp.alchemy-fox.de/'
LINKS = (('GitHub-Repo', GITHUB_URL), ('Alchemy Fox', SITE_URL),
         ('Guide-Seite', GUIDE_URL), ('Community', COMMUNITY_URL))


# ---------------------------------------------------------------------------
#  Sprache: Englisch ist Standard, Deutsch wenn Windows auf Deutsch laeuft.
#  Umschaltbar in der Einstellungsdatei ("sprache": "de"/"en") oder ueber die
#  Umgebungsvariable MINIMAP_TOOL_LANG. Deutsche Texte sind die Quelle, die
#  englische Tabelle steht unten (TEXTE_EN).
# ---------------------------------------------------------------------------

def _windows_ui_sprache():
    try:
        import ctypes
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return 'de' if (lang_id & 0x3FF) == 0x07 else 'en'
    except Exception:
        import locale
        loc = (locale.getlocale()[0] or '').lower()
        return 'de' if loc.startswith('de') or 'german' in loc else 'en'


def _sprache_bestimmen():
    env = os.environ.get('MINIMAP_TOOL_LANG', '').lower()
    if env in ('de', 'en'):
        return env
    try:
        import json
        with open(os.path.join(DATEN, 'minimap_tool_settings.json'), encoding='utf-8') as f:
            st = json.load(f).get('sprache', '')
        if st in ('de', 'en'):
            return st
    except Exception:
        pass
    return _windows_ui_sprache()


SPRACHE = _sprache_bestimmen()


def tr(text, **kw):
    """Deutscher Quelltext -> Anzeigetext in der aktuellen Sprache."""
    if SPRACHE == 'en':
        text = TEXTE_EN.get(text, text)
    return text.format(**kw) if kw else text

B = chr(92)
LEVELS_WD = os.path.join(WDFILES, 'Levels.wd')
OUT_DEFAULT = os.path.join(DATEN, 'minimap')
MODS_DIR = os.path.join(SPIEL, 'Mods')
MOD_NAME = 'Minimap'                                # Mods\Minimap.wd
REG_MODS = r'SOFTWARE\Reality Pump\TwoWorlds\Mods'   # <Archiv>.wd = 1 schaltet ein
INNEN = B.join(['Levels', 'MipMaps', ''])          # Archivpfad-Praefix
KANTE = {0: 512, 1: 256, 2: 128, 3: 64}
BYTES = {0: 131200, 1: 32896, 2: 8320, 3: 2176}   # 128 Kopf + DXT1-Bloecke
NAME_RE = re.compile(r'^([A-Za-z])(-?\d{1,2})(_1)?$')
EBENEN = ('Oberfläche', 'Unterwelt')   # so heissen sie auf der Kartenseite im Spiel
# Retail belegt A-I / 1-12. Das Raster zeigt rundherum zwei Reihen leere
# Felder fuer neue Karten: Spalten Y, Z vor A und J, K nach I, Reihen -1 und
# 0 vor 1 sowie 13 und 14 nach 12. Ob das Spiel solche Zellnamen als Karte
# annimmt, ist ungemessen - fuer die Minimap ist der Name frei.
COL_ORDER = ['Y', 'Z'] + [chr(c) for c in range(ord('A'), ord('K') + 1)]
ROW_RANGE = range(-1, 15)


def col_index(col):
    """Sortierschluessel: Y, Z, A ... K; alles andere dahinter alphabetisch."""
    return COL_ORDER.index(col) if col in COL_ORDER else len(COL_ORDER) + ord(col)


def name_von(col, row, ebene):
    """Zellname nach Retail-Regel: 1-9 mit fuehrender Null, 0 als 00, -1 als -1."""
    if row < 0:
        n = f'{col}{row}'
    elif row < 10:
        n = f'{col}{row:02d}'
    else:
        n = f'{col}{row}'
    return n + ('_1' if ebene else '')


# ---------------------------------------------------------------------------
#  Namen und Archiv
# ---------------------------------------------------------------------------

def zellname(text):
    """'e6' / 'E06' / 'f1_1' / 'z-1' -> ('E06', 'E', 6, 0), ('F01_1', 'F', 1, 1), ('Z-1', 'Z', -1, 0)."""
    m = NAME_RE.match(text.strip())
    if not m:
        return None
    col = m.group(1).upper()
    row = int(m.group(2))
    if row < -9 or row > 99:
        return None
    ebene = 1 if m.group(3) else 0
    return name_von(col, row, ebene), col, row, ebene


def aus_wd(archiv, innen):
    """Eine Datei aus einem WD-Archiv, entpackt."""
    for e in wd_metadaten.eintraege(archiv):
        if e['pfad'].lower() == innen.lower():
            with open(archiv, 'rb') as f:
                f.seek(e['offset'])
                roh = f.read(e['clen'])
            if e['flags'] & 1:
                d = zlib.decompressobj()
                roh = d.decompress(roh) + d.flush()
            return roh
    return None


def dds_lesen(roh):
    return Image.open(io.BytesIO(roh)).convert('RGB')


def dds_schreiben(bild):
    """RGB-Bild (quadratisch, Kante 4er-Vielfaches) als DXT1 ohne Mipmaps."""
    buf = io.BytesIO()
    bild.save(buf, format='DDS', pixel_format='DXT1')
    roh = buf.getvalue()
    kante = bild.size[0]
    soll = 128 + (kante // 4) ** 2 * 8
    if roh[84:88] != b'DXT1' or len(roh) != soll:
        raise ValueError(tr('Pillow hat kein reines DXT1 geschrieben ({ist} B statt {soll} B)', ist=len(roh), soll=soll))
    return roh


def stufen(bild512):
    """Die vier DDS-Stufen aus dem 512er-Bild: {0: bytes, 1: ..., 3: ...}."""
    aus = {}
    for s, k in KANTE.items():
        b = bild512 if k == 512 else bild512.resize((k, k), Image.LANCZOS)
        roh = dds_schreiben(b)
        if len(roh) != BYTES[s]:
            raise ValueError(tr('Stufe {s}: {ist} B statt {soll} B', s=s, ist=len(roh), soll=BYTES[s]))
        aus[s] = roh
    return aus


def bild_einpassen(pfad):
    """Beliebiges Bild -> 512x512 RGB. Kleiner als 512 wird abgelehnt."""
    im = Image.open(pfad)
    im.load()
    im = im.convert('RGB')
    w, h = im.size
    if min(w, h) < 512:
        raise ValueError(tr('{datei}: {w}x{h} px - mindestens 512 px je Seite', datei=os.path.basename(pfad), w=w, h=h))
    if w != h:                       # mittig quadratisch beschneiden
        k = min(w, h)
        x, y = (w - k) // 2, (h - k) // 2
        im = im.crop((x, y, x + k, y + k))
    if im.size[0] != 512:
        im = im.resize((512, 512), Image.LANCZOS)
    return im


# ---------------------------------------------------------------------------
#  Datenmodell
# ---------------------------------------------------------------------------

class Kachel:
    __slots__ = ('name', 'col', 'row', 'ebene', 'retail_roh', 'mod_pfad',
                 '_retail', '_mod', 'neu', '_cache')

    def __init__(self, name, col, row, ebene):
        self.name, self.col, self.row, self.ebene = name, col, row, ebene
        self.retail_roh = None      # DDS-Bytes der 512er Retail-Stufe
        self.mod_pfad = None        # Map_<Zelle>@0.dds im Ausgabeordner
        self._retail = None
        self._mod = None
        self.neu = None             # PIL 512, ungespeichert
        self._cache = {}

    @property
    def quelle(self):
        if self.neu is not None:
            return 'neu'
        if self.mod_pfad:
            return 'Mod'
        if self.retail_roh:
            return 'Retail'
        return '-'

    def retail(self):
        if self._retail is None and self.retail_roh:
            self._retail = dds_lesen(self.retail_roh)
        return self._retail

    def mod(self):
        if self._mod is None and self.mod_pfad:
            with open(self.mod_pfad, 'rb') as f:
                self._mod = dds_lesen(f.read())
        return self._mod

    def bild(self):
        """Was das Spiel zeigen wuerde, in Sitzungsreihenfolge: neu > Mod > Retail."""
        if self.neu is not None:
            return self.neu
        return self.mod() or self.retail()

    def vorschau(self, kante):
        key = (kante, id(self.bild()))
        if key not in self._cache:
            self._cache.clear()
            b = self.bild()
            self._cache[key] = None if b is None else b.resize((kante, kante), Image.BILINEAR)
        return self._cache[key]


class Modell:
    def __init__(self, ausgabe):
        self.ausgabe = ausgabe
        self.kacheln = {}           # name -> Kachel

    def laden(self, fortschritt=None):
        self.kacheln.clear()
        if os.path.exists(LEVELS_WD):
            eintr = [e for e in wd_metadaten.eintraege(LEVELS_WD)
                     if e['pfad'].lower().startswith(INNEN.lower())
                     and e['pfad'].lower().endswith('@0.dds')]
            with open(LEVELS_WD, 'rb') as f:
                for i, e in enumerate(eintr):
                    base = e['pfad'][len(INNEN):-len('@0.dds')]
                    if not base.lower().startswith('map_'):
                        continue
                    z = zellname(base[4:])
                    if not z:
                        continue
                    f.seek(e['offset'])
                    roh = f.read(e['clen'])
                    if e['flags'] & 1:
                        d = zlib.decompressobj()
                        roh = d.decompress(roh) + d.flush()
                    k = self.kachel(*z)
                    k.retail_roh = roh
                    if fortschritt and i % 20 == 0:
                        fortschritt(f'Levels.wd: {i}/{len(eintr)}')
        self.mod_dateien_lesen()

    def mod_dateien_lesen(self):
        for k in self.kacheln.values():
            k.mod_pfad = None
            k._mod = None
            k._cache.clear()
        if not os.path.isdir(self.ausgabe):
            return
        for fn in os.listdir(self.ausgabe):
            m = re.match(r'^Map_(.+)@0\.dds$', fn, re.I)
            if not m:
                continue
            z = zellname(m.group(1))
            if not z:
                continue
            k = self.kachel(*z)
            k.mod_pfad = os.path.join(self.ausgabe, fn)
        # Kacheln ohne Retail und ohne Mod-Datei (z. B. abgebrochene Tour) raeumen
        for name in [n for n, k in self.kacheln.items() if not k.retail_roh and not k.mod_pfad and k.neu is None]:
            del self.kacheln[name]

    def kachel(self, name, col, row, ebene):
        k = self.kacheln.get(name)
        if k is None:
            k = Kachel(name, col, row, ebene)
            self.kacheln[name] = k
        return k

    def raster(self, ebene):
        """(Spalten, Reihen) der Ebene: Y-K / -1..14 plus alles, was darueber hinausgeht."""
        cols = set(COL_ORDER)
        rows = set(ROW_RANGE)
        for k in self.kacheln.values():
            if k.ebene == ebene:
                cols.add(k.col)
                rows.add(k.row)
        return sorted(cols, key=col_index), sorted(rows)

    def geaendert(self):
        return [k for k in self.kacheln.values() if k.neu is not None]

    # -- Sicherung: vor jeder Aenderung liegt der vorherige Stand in backup\ ----

    @property
    def backup(self):
        return os.path.join(self.ausgabe, 'backup')

    def sichern(self, kachel):
        """Den Stand, den das Spiel bis jetzt zeigte, wegsichern.

        Retail (alle vier Stufen aus Levels.wd) nach backup\\retail\\ - einmalig,
        wird nie ueberschrieben. Eine schon vorhandene Mod-Fassung aus dem
        Ausgabeordner nach backup\\<Datum_Uhrzeit>\\, damit auch der zweite
        Tausch derselben Kachel nichts verliert.
        """
        if kachel.retail_roh:
            ziel = os.path.join(self.backup, 'retail')
            os.makedirs(ziel, exist_ok=True)
            for s in KANTE:
                p = os.path.join(ziel, f'Map_{kachel.name}@{s}.dds')
                if os.path.exists(p):
                    continue
                roh = aus_wd(LEVELS_WD, f'{INNEN}Map_{kachel.name}@{s}.dds')
                if roh is None:
                    continue
                with open(p, 'wb') as f:
                    f.write(roh)
        if kachel.mod_pfad:
            import shutil
            import time
            ziel = os.path.join(self.backup, time.strftime('%Y-%m-%d_%H-%M-%S'))
            os.makedirs(ziel, exist_ok=True)
            for s in KANTE:
                p = os.path.join(self.ausgabe, f'Map_{kachel.name}@{s}.dds')
                if os.path.exists(p):
                    shutil.copy2(p, ziel)

    def speichern(self, kachel):
        os.makedirs(self.ausgabe, exist_ok=True)
        self.sichern(kachel)
        st = stufen(kachel.neu)
        for s, roh in st.items():
            pfad = os.path.join(self.ausgabe, f'Map_{kachel.name}@{s}.dds')
            with open(pfad, 'wb') as f:
                f.write(roh)
            if os.path.getsize(pfad) != BYTES[s]:
                raise ValueError(tr('{pfad}: {ist} B statt {soll} B', pfad=pfad, ist=os.path.getsize(pfad), soll=BYTES[s]))
        kachel.mod_pfad = os.path.join(self.ausgabe, f'Map_{kachel.name}@0.dds')
        kachel._mod = kachel.neu
        kachel.neu = None
        kachel._cache.clear()

    def retail_wiederherstellen(self, kachel):
        self.sichern(kachel)          # die verworfene Mod-Fassung bleibt im backup\
        for s in KANTE:
            p = os.path.join(self.ausgabe, f'Map_{kachel.name}@{s}.dds')
            if os.path.exists(p):
                os.remove(p)
        kachel.mod_pfad = None
        kachel._mod = None
        kachel.neu = None
        kachel._cache.clear()
        if not kachel.retail_roh:
            del self.kacheln[kachel.name]

    def mod_dateien(self):
        """{Archivpfad: bytes} aller DDS im Ausgabeordner."""
        aus = {}
        if not os.path.isdir(self.ausgabe):
            return aus
        for fn in sorted(os.listdir(self.ausgabe)):
            m = re.match(r'^Map_(.+)@([0-3])\.dds$', fn, re.I)
            if not m:
                continue
            p = os.path.join(self.ausgabe, fn)
            if os.path.getsize(p) != BYTES[int(m.group(2))]:
                raise ValueError(tr('{pfad}: {ist} B statt {soll} B', pfad=fn, ist=os.path.getsize(p), soll=BYTES[int(m.group(2))]))
            with open(p, 'rb') as f:
                aus[INNEN + fn] = f.read()
        return aus

    # -- ins Spiel ------------------------------------------------------------

    def ins_spiel(self, name=MOD_NAME):
        """Alle DDS des Ausgabeordners als Mods\\<name>.wd packen und aktivieren.

        Retail-Archive werden nie angefasst: das Spiel legt Mod-Archive ueber
        Levels.wd, wenn sie unter HKCU\\...\\TwoWorlds\\Mods auf 1 stehen.
        Gepackt wird ueber packer.pack_mod (buglords wdio), das einzige
        Verfahren, dessen Archive das Spiel nachweislich laedt.
        """
        import packer
        dateien = self.mod_dateien()
        if not dateien:
            raise ValueError(tr('keine DDS im Ausgabeordner'))
        if not os.path.isdir(MODS_DIR):
            raise ValueError(tr('Mods-Ordner fehlt: {pfad}', pfad=MODS_DIR))
        out = packer.pack_mod(MODS_DIR, name, dateien)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_MODS) as k:
            winreg.SetValueEx(k, f'{name}.wd', 0, winreg.REG_DWORD, 1)
        return out, len(dateien)

    @staticmethod
    def spiel_laeuft():
        try:
            import subprocess
            r = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq TwoWorlds*'], capture_output=True, text=True)
            return 'TwoWorlds' in r.stdout
        except Exception:
            return False

    def ebene_bild(self, ebene, kante=512):
        cols, rows = self.raster(ebene)
        big = Image.new('RGB', (kante * len(cols), kante * len(rows)), (40, 40, 40))
        for k in self.kacheln.values():
            if k.ebene != ebene:
                continue
            b = k.bild()
            if b is None:
                continue
            if b.size[0] != kante:
                b = b.resize((kante, kante), Image.LANCZOS)
            big.paste(b, (cols.index(k.col) * kante, rows.index(k.row) * kante))
        return big


# ---------------------------------------------------------------------------
#  Oberflaeche
# ---------------------------------------------------------------------------

def bildtypen():
    return [(tr('Bilder'), '*.png *.jpg *.jpeg *.bmp *.dds *.tga *.tif *.tiff'),
            ('PNG', '*.png'), ('JPEG', '*.jpg *.jpeg'), ('DDS', '*.dds'),
            (tr('Alle Dateien'), '*.*')]
RAND = 28          # Platz fuer die Beschriftung A-I / 1-12
VORSCHAU_PX = 264  # feste Kantenlaenge der Kachelvorschau rechts


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()                      # erst fertig bauen, dann zeigen
        theme.apply_dark_theme(self)
        self.title('TW1 Minimap Tool')
        ico = os.path.join(RES, 'minimap_tool.ico')
        if os.path.exists(ico):
            try:
                self.iconbitmap(default=ico)
            except tk.TclError:
                pass
        self.tour = None
        self.tour_ziel = None
        self.geometry('1280x860')
        self.minsize(960, 700)
        self.modell = Modell(OUT_DEFAULT)
        self.ebene = tk.IntVar(value=0)
        self.zoom = 72
        self.zeige_linien = tk.BooleanVar(value=True)
        self.zeige_namen = tk.BooleanVar(value=True)
        self.auswahl = None
        self.fotos = {}
        self.suchtext = tk.StringVar()
        self._menue()
        self._werkzeugleiste()
        self._statusleiste()      # vor dem Kartenbereich packen, sonst wird sie bei kleinem Fenster verdraengt
        self._koerper()
        self.bind('<Control-o>', lambda e: self.bild_einlegen())
        self.bind('<Control-e>', lambda e: self.exportieren())
        self.bind('<Control-n>', lambda e: self.neues_tile())
        self.bind('<Control-s>', lambda e: self.speichern())
        self.bind('<Control-g>', lambda e: self.ins_spiel())
        self.bind('<F1>', lambda e: self.ebene_setzen(0))
        self.bind('<F2>', lambda e: self.ebene_setzen(1))
        self.bind('<Control-f>', lambda e: self.suche.focus_set())
        self.protocol('WM_DELETE_WINDOW', self.beenden)
        self.deiconify()
        self.after(50, self.laden)
        if not einstellungen_lesen().get('tour_gesehen'):
            self.after(2500, self.tour_starten)

    # -- Aufbau -------------------------------------------------------------

    def _menue(self):
        """Dunkle Menueleiste (Frame + Labels), jedes Label oeffnet ein theme.Menu."""
        self.sprache_var = tk.StringVar(value=SPRACHE)
        bar = ttk.Frame(self, style='Menubar.TFrame')
        bar.pack(side='top', fill='x')
        self.menubar = bar
        for key, filler in ((tr('Datei'), self._fill_datei), (tr('Bearbeiten'), self._fill_bearbeiten),
                            (tr('Ansicht'), self._fill_ansicht), (tr('Hilfe'), self._fill_hilfe)):
            item = ttk.Label(bar, text=key, style='Menubar.TLabel')
            item.pack(side='left')
            item.bind('<Button-1>', lambda ev, f=filler, w=item: self._popup(f, w))
            item.bind('<Enter>', lambda ev, w=item: w.state(['active']))
            item.bind('<Leave>', lambda ev, w=item: w.state(['!active']))
        ttk.Label(bar, text='TW1 MINIMAP TOOL', style='Menubar.TLabel').pack(side='right', padx=(0, 6))

    def _popup(self, filler, widget):
        menu = theme.Menu(self)
        filler(menu)
        try:
            menu.tk_popup(widget.winfo_rootx(), widget.winfo_rooty() + widget.winfo_height())
        finally:
            menu.grab_release()

    def _fill_datei(self, m):
        strg = tr('Strg')
        m.add_command(label=tr('Bild einlegen...'), accelerator=strg + '+O', command=self.bild_einlegen)
        m.add_command(label=tr('Kachel exportieren...'), accelerator=strg + '+E', command=self.exportieren)
        m.add_command(label=tr('Ganze Ebene exportieren...'), command=self.ebene_exportieren)
        m.add_separator()
        m.add_command(label=tr('Neues Tile...'), accelerator=strg + '+N', command=self.neues_tile)
        m.add_separator()
        m.add_command(label=tr('Aenderungen speichern'), accelerator=strg + '+S', command=self.speichern,
                      state='normal' if self.modell.geaendert() else 'disabled')
        m.add_command(label=tr('Ins Spiel uebernehmen (Mods\\Minimap.wd)'), accelerator=strg + '+G', command=self.ins_spiel)
        m.add_command(label=tr('Als Mod-Archiv (.wd) woanders packen...'), command=self.wd_packen)
        m.add_command(label=tr('Sicherungsordner oeffnen'), command=self.backup_oeffnen)
        m.add_command(label=tr('Ausgabeordner waehlen...'), command=self.ausgabe_waehlen)
        m.add_separator()
        m.add_command(label=tr('Beenden'), command=self.beenden)

    def _fill_bearbeiten(self, m):
        k = self.auswahl
        m.add_command(label=tr('Aenderung dieser Kachel verwerfen'), command=self.verwerfen,
                      state='normal' if k is not None and k.neu is not None else 'disabled')
        m.add_command(label=tr('Alle ungespeicherten Aenderungen verwerfen'), command=self.alle_verwerfen,
                      state='normal' if self.modell.geaendert() else 'disabled')
        m.add_separator()
        m.add_command(label=tr('Kachel auf Retail zuruecksetzen (Mod-Dateien loeschen)'), command=self.retail_zurueck,
                      state='normal' if k is not None and (k.mod_pfad or k.neu is not None) else 'disabled')

    def _fill_ansicht(self, m):
        m.add_radiobutton(label=tr('Oberfläche'), accelerator='F1', variable=self.ebene, value=0, command=self.zeichnen)
        m.add_radiobutton(label=tr('Unterwelt'), accelerator='F2', variable=self.ebene, value=1, command=self.zeichnen)
        m.add_separator()
        m.add_command(label=tr('Vergroessern'), accelerator=tr('Mausrad'), command=lambda: self.zoomen(1))
        m.add_command(label=tr('Verkleinern'), command=lambda: self.zoomen(-1))
        m.add_command(label=tr('Einpassen'), command=self.einpassen)
        m.add_separator()
        m.add_checkbutton(label=tr('Trennlinien zwischen den Kacheln'), variable=self.zeige_linien, command=self.zeichnen)
        m.add_checkbutton(label=tr('Kachelnamen'), variable=self.zeige_namen, command=self.zeichnen)
        m.add_separator()
        sprache = theme.Menu(m)
        sprache.add_radiobutton(label='English', variable=self.sprache_var, value='en', command=self.sprache_wechseln)
        sprache.add_radiobutton(label='Deutsch', variable=self.sprache_var, value='de', command=self.sprache_wechseln)
        m.add_cascade(label='Language / Sprache', menu=sprache)
        m.add_separator()
        m.add_command(label=tr('Neu laden'), command=self.laden)

    def _fill_hilfe(self, m):
        m.add_command(label=tr('Einfuehrung (Schritt fuer Schritt)...'), command=self.tour_starten)
        m.add_command(label=tr('Kurzanleitung'), command=self.anleitung)
        m.add_separator()
        for name, url in LINKS:
            m.add_command(label=f'{tr(name)}  ({url})', command=lambda u=url: webbrowser.open(u))
        m.add_separator()
        m.add_command(label=tr('Ueber'), command=self.ueber)

    def ueber(self):
        win = tk.Toplevel(self)
        win.title(tr('Ueber'))
        win.transient(self)
        win.resizable(False, False)
        win.configure(background=BG)
        theme.dark_titlebar(win)
        f = ttk.Frame(win, padding=20)
        f.pack(fill='both', expand=True)
        ttk.Label(f, text='TW1 Minimap Tool', style='Brand.TLabel').pack(anchor='w')
        ttk.Label(f, text=tr('Version {v}', v=VERSION), style='Muted.TLabel').pack(anchor='w', pady=(0, 10))
        ttk.Label(f, text=tr(UEBER_TEXT), style='Muted.TLabel', wraplength=420, justify='left').pack(anchor='w', pady=(0, 10))
        for name, url in LINKS:
            lnk = ttk.Label(f, text=f'{tr(name)}: {url}', style='Link.TLabel', cursor='hand2')
            lnk.pack(anchor='w', padx=(12, 0))
            lnk.bind('<Button-1>', lambda e, u=url: webbrowser.open(u))
        ttk.Label(f, text=tr('Minimap-Kacheln aus Two Worlds 1 (Reality Pump, 2007). Packen ueber wdio von buglord.'),
                  style='Muted.TLabel', wraplength=420, justify='left').pack(anchor='w', pady=(12, 0))
        ttk.Button(f, text=tr('Schliessen'), command=win.destroy).pack(anchor='e', pady=(16, 0))
        win.bind('<Escape>', lambda e: win.destroy())
        win.update_idletasks()
        win.geometry(f'+{self.winfo_rootx() + 120}+{self.winfo_rooty() + 100}')

    def _werkzeugleiste(self):
        tb = ttk.Frame(self, padding=(8, 5), style='Panel.TFrame')
        tb.pack(side='top', fill='x')
        ttk.Label(tb, text=tr('Suche:'), style='Panel.TLabel').pack(side='left')
        self.suche = ttk.Entry(tb, textvariable=self.suchtext, width=10)
        self.suche.pack(side='left', padx=4)
        self.suche.bind('<Return>', lambda e: self.suchen())
        ttk.Button(tb, text=tr('Gehe zu'), command=self.suchen).pack(side='left')
        ttk.Separator(tb, orient='vertical').pack(side='left', fill='y', padx=10)
        ttk.Button(tb, text=tr('Neues Tile'), command=self.neues_tile).pack(side='left', padx=2)
        self.knoepfe = {}
        def knopf(name, **kw):
            b = ttk.Button(tb, **kw)
            b.pack(side='left', padx=2)
            self.knoepfe.setdefault(name, []).append(b)
            return b
        knopf('bild_einlegen', text=tr('Bild einlegen'), command=self.bild_einlegen)
        knopf('exportieren', text=tr('Exportieren'), command=self.exportieren)
        knopf('speichern', text=tr('Speichern'), command=self.speichern)
        knopf('ins_spiel', text=tr('Ins Spiel uebernehmen'), command=self.ins_spiel, style='Accent.TButton')
        ttk.Separator(tb, orient='vertical').pack(side='left', fill='y', padx=10)
        ttk.Button(tb, text='-', width=3, command=lambda: self.zoomen(-1)).pack(side='left')
        self.zoomlabel = ttk.Label(tb, text='72 px', width=7, anchor='center', style='PanelMuted.TLabel')
        self.zoomlabel.pack(side='left')
        ttk.Button(tb, text='+', width=3, command=lambda: self.zoomen(1)).pack(side='left')
        ttk.Button(tb, text=tr('Einpassen'), command=self.einpassen).pack(side='left', padx=(4, 0))
        ttk.Separator(tb, orient='vertical').pack(side='left', fill='y', padx=10)
        ttk.Checkbutton(tb, text=tr('Linien'), variable=self.zeige_linien, command=self.zeichnen, style='Panel.TCheckbutton').pack(side='left')
        ttk.Checkbutton(tb, text=tr('Namen'), variable=self.zeige_namen, command=self.zeichnen, style='Panel.TCheckbutton').pack(side='left', padx=(6, 0))

    def _koerper(self):
        pw = ttk.PanedWindow(self, orient='horizontal')
        pw.pack(fill='both', expand=True)
        self.pw = pw

        # links: Karte
        links = ttk.Frame(pw, width=900)
        pw.add(links, weight=4)
        self.canvas = tk.Canvas(links, background=CANVAS_BG, highlightthickness=0, width=880, height=720)
        vs = ttk.Scrollbar(links, orient='vertical', command=self.canvas.yview)
        hs = ttk.Scrollbar(links, orient='horizontal', command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        vs.grid(row=0, column=1, sticky='ns')
        hs.grid(row=1, column=0, sticky='ew')
        links.rowconfigure(0, weight=1)
        links.columnconfigure(0, weight=1)
        # Ebenenwahl unten rechts auf der Karte, wie im Spiel: Pfeil hoch =
        # Oberwelt, Pfeil runter = Untergrund
        eb = tk.Frame(links, background=PANEL, highlightthickness=1, highlightbackground=LINE)
        eb.place(relx=1.0, rely=1.0, anchor='se', x=-24, y=-24)
        knopf_kw = dict(background=PANEL, foreground=INK, activebackground=SEL, activeforeground=GOLD_HI,
                        disabledforeground=DIM, relief='flat', font=('Segoe UI', 11, 'bold'), cursor='hand2',
                        borderwidth=0, highlightthickness=0)
        self.ebene_hoch = tk.Button(eb, text='▲', width=3, command=lambda: self.ebene_setzen(0), **knopf_kw)
        self.ebene_hoch.pack(fill='x')
        self.ebene_text = tk.Label(eb, text=tr(EBENEN[0]), width=11, background=PANEL, foreground=GOLD, font=FONT_BOLD)
        self.ebene_text.pack(fill='x', pady=2)
        self.ebene_runter = tk.Button(eb, text='▼', width=3, command=lambda: self.ebene_setzen(1), **knopf_kw)
        self.ebene_runter.pack(fill='x')
        self.bind('<Prior>', lambda e: self.ebene_setzen(0))      # Bild hoch
        self.bind('<Next>', lambda e: self.ebene_setzen(1))       # Bild runter
        # Fenstergroesse geaendert (z. B. maximiert): solange nicht von Hand
        # gezoomt wurde, die Karte neu einpassen, sonst nur neu zentrieren
        self._auto_fit = True
        self._configure_job = None
        self.canvas.bind('<Configure>', self._canvas_configure)
        self.canvas.bind('<Button-1>', self.klick)
        self.canvas.bind('<Double-Button-1>', lambda e: self.bild_einlegen())
        # Mausrad zoomt um den Zeiger; Shift+Rad rollt waagerecht, Strg+Rad senkrecht
        self.canvas.bind('<MouseWheel>', lambda e: self.zoomen(1 if e.delta > 0 else -1, (e.x, e.y)))
        self.canvas.bind('<Shift-MouseWheel>', lambda e: self.canvas.xview_scroll(-1 if e.delta > 0 else 1, 'units'))
        self.canvas.bind('<Control-MouseWheel>', lambda e: self.canvas.yview_scroll(-1 if e.delta > 0 else 1, 'units'))
        # Ziehen mit der mittleren oder rechten Maustaste verschiebt die Karte
        self.canvas.bind('<ButtonPress-2>', lambda e: self.canvas.scan_mark(e.x, e.y))
        self.canvas.bind('<B2-Motion>', lambda e: self.canvas.scan_dragto(e.x, e.y, gain=1))
        self.canvas.bind('<ButtonPress-3>', lambda e: self.canvas.scan_mark(e.x, e.y))
        self.canvas.bind('<B3-Motion>', lambda e: self.canvas.scan_dragto(e.x, e.y, gain=1))

        # rechts: Dateiliste + Auswahl
        rechts = ttk.Frame(pw, padding=(0, 0), width=320, style='Panel.TFrame')
        pw.add(rechts, weight=0)
        self.after(100, lambda: pw.sashpos(0, max(600, self.winfo_width() - 360)))
        ttk.Label(rechts, text=tr('Kacheln dieser Ebene').upper(), style='PanelTitle.TLabel').pack(anchor='w', fill='x')
        lf = ttk.Frame(rechts, style='Panel.TFrame', padding=(8, 0))
        lf.pack(fill='both', expand=True)
        self.liste = ttk.Treeview(lf, columns=('zelle', 'quelle', 'status'), show='headings', selectmode='browse', height=6)
        self.liste.heading('zelle', text=tr('Zelle'))
        self.liste.heading('quelle', text=tr('Quelle'))
        self.liste.heading('status', text=tr('Status'))
        self.liste.column('zelle', width=70, anchor='w', stretch=False)
        self.liste.column('quelle', width=60, anchor='w', stretch=False)
        self.liste.column('status', width=110, anchor='w')
        ls = ttk.Scrollbar(lf, orient='vertical', command=self.liste.yview)
        self.liste.configure(yscrollcommand=ls.set)
        self.liste.pack(side='left', fill='both', expand=True)
        ls.pack(side='right', fill='y')
        self.liste.bind('<<TreeviewSelect>>', self.liste_auswahl)
        self.liste.tag_configure('neu', foreground=FARBE_NEU)
        self.liste.tag_configure('mod', foreground=FARBE_MOD)

        # Von unten her packen: Knoepfe und die feste Vorschau sind immer zu
        # sehen, die Kachelliste darueber bekommt den restlichen Platz.
        bf = ttk.Frame(rechts, style='Panel.TFrame', padding=(8, 0))
        bf.pack(side='bottom', fill='x', pady=(4, 8))
        for reihe in ((('bild_einlegen', tr('Bild einlegen...'), self.bild_einlegen),
                       ('exportieren', tr('Exportieren...'), self.exportieren)),
                      (('verwerfen', tr('Verwerfen'), self.verwerfen),
                       ('retail_zurueck', tr('Retail zurueck'), self.retail_zurueck))):
            rf = ttk.Frame(bf, style='Panel.TFrame')
            rf.pack(fill='x', pady=2)
            for name, text, cmd in reihe:
                b = ttk.Button(rf, text=text, command=cmd)
                b.pack(side='left', fill='x', expand=True, padx=3)
                self.knoepfe.setdefault(name, []).append(b)
        self.vorschau_label = ttk.Label(rechts, text=tr('Vorschau der Kachel (512 px, verkleinert)'),
                                        style='PanelMuted.TLabel', wraplength=290, padding=(8, 2))
        self.vorschau_label.pack(side='bottom', anchor='w')
        # feste Vorschau ohne Zoom: die 512er-Kachel auf VORSCHAU_PX verkleinert
        vf = ttk.Frame(rechts, style='Panel.TFrame', padding=(8, 0))
        vf.pack(side='bottom', fill='x')
        self.vorschau = tk.Canvas(vf, background=CANVAS_BG, highlightthickness=1, highlightbackground=LINE,
                                  width=VORSCHAU_PX, height=VORSCHAU_PX)
        self.vorschau.pack()
        self.info = ttk.Label(rechts, text='-', justify='left', style='Panel.TLabel', padding=(8, 0))
        self.info.pack(side='bottom', anchor='w', fill='x', pady=(0, 4))
        ttk.Label(rechts, text=tr('Ausgewaehlte Kachel').upper(), style='PanelTitle.TLabel').pack(side='bottom', anchor='w', fill='x', pady=(8, 0))

    def _statusleiste(self):
        leiste = ttk.Frame(self, style='Status.TFrame')
        leiste.pack(side='bottom', fill='x')
        self.status = ttk.Label(leiste, text='', anchor='w', style='Status.TLabel')
        self.status.pack(side='left', fill='x', expand=True)

    def melden(self, text, art=None):
        """Statuszeile; art 'ok' gruen, 'err' rot, sonst gedaempft."""
        self.status.config(text=text, style={'ok': 'StatusOk.TLabel', 'err': 'StatusErr.TLabel'}.get(art, 'Status.TLabel'))
        self.update_idletasks()

    # -- Laden / Zeichnen ---------------------------------------------------

    def laden(self):
        if self.modell.geaendert():
            if not messagebox.askyesno(tr('Neu laden'), tr('Ungespeicherte Aenderungen gehen verloren. Trotzdem neu laden?')):
                return
        if not os.path.exists(LEVELS_WD):
            messagebox.showerror(tr('Levels.wd fehlt'), tr('Nicht gefunden:\n{pfad}', pfad=LEVELS_WD))
        self.melden(tr('Lade Levels.wd ...'))
        try:
            self.modell.laden(self.melden)
        except Exception as ex:
            messagebox.showerror(tr('Laden fehlgeschlagen'), str(ex))
        self.auswahl = None
        n_ob = sum(1 for k in self.modell.kacheln.values() if k.ebene == 0)
        n_un = len(self.modell.kacheln) - n_ob
        self.melden(tr('{n_ob} Kacheln Oberfläche, {n_un} Unterwelt - Ausgabe: {pfad}', n_ob=n_ob, n_un=n_un, pfad=self.modell.ausgabe))
        self.after(250, self.einpassen)     # erst wenn der Kartenbereich seine Groesse hat

    def ebene_setzen(self, e):
        if self.ebene.get() == e:
            return
        self.ebene.set(e)
        self.einpassen() if self._auto_fit else self.zeichnen()

    ZOOMSTUFEN = [24, 32, 40, 48, 56, 64, 72, 80, 96, 112, 128, 160, 192, 256, 320, 384, 448, 512]

    def zoomen(self, richtung, anker=None):
        """Eine Stufe rein/raus. Mit anker=(x, y) bleibt der Punkt unter dem Zeiger stehen."""
        st = self.ZOOMSTUFEN
        naeher = min(st, key=lambda s: abs(s - self.zoom))
        i = max(0, min(len(st) - 1, st.index(naeher) + richtung))
        if st[i] == self.zoom:
            return
        self._auto_fit = False
        alt = self.zoom
        c = self.canvas
        if anker is None:
            anker = (c.winfo_width() / 2, c.winfo_height() / 2)
        # Kartenkoordinate unter dem Anker, in Kacheleinheiten
        kx = (c.canvasx(anker[0]) - self._ox) / alt
        ky = (c.canvasy(anker[1]) - self._oy) / alt
        self.zoom = st[i]
        self.zeichnen()
        self._ansicht_auf(self._ox + kx * self.zoom - anker[0], self._oy + ky * self.zoom - anker[1])

    def _canvas_configure(self, ev):
        if self._configure_job:
            self.after_cancel(self._configure_job)
        self._configure_job = self.after(150, self._nach_groessenwechsel)

    def _nach_groessenwechsel(self):
        self._configure_job = None
        if not self.modell.kacheln:
            return
        if self._auto_fit:
            self.einpassen()
        else:
            self.zeichnen()

    def _ansicht_auf(self, x, y):
        """Linke obere Ecke des Sichtfensters auf Leinwandpunkt (x, y) legen."""
        sr = self.canvas.cget('scrollregion').split()
        w, h = float(sr[2]), float(sr[3])
        self.canvas.xview_moveto(max(0.0, min(1.0, x / w)))
        self.canvas.yview_moveto(max(0.0, min(1.0, y / h)))

    def einpassen(self):
        """Ausgewaehlte Kachel formatfuellend, sonst die ganze Ebene."""
        self.update_idletasks()
        w = max(200, self.canvas.winfo_width() - RAND - 8)
        h = max(200, self.canvas.winfo_height() - RAND - 8)
        k = self.auswahl
        if k is not None and k.ebene == self.ebene.get():
            self._auto_fit = False
            ziel = min(w, h) - 16
            self.zoom = max(s for s in self.ZOOMSTUFEN if s <= ziel) if ziel >= 24 else 24
            self.zeichnen()
            self.sichtbar_machen(k)
            return
        self._auto_fit = True
        cols, rows = self.modell.raster(self.ebene.get())
        self.zoom = max(24, min(512, min(w // len(cols), h // len(rows))))
        self.zeichnen()
        self._ansicht_auf(0, 0)

    def zeichnen(self):
        c = self.canvas
        c.delete('all')
        self.fotos.clear()
        eb = self.ebene.get()
        cols, rows = self.modell.raster(eb)
        z = self.zoom
        self.zoomlabel.config(text=f'{z} px')
        self.ebene_text.config(text=tr(EBENEN[eb]))
        self.ebene_hoch.config(state='disabled' if eb == 0 else 'normal')
        self.ebene_runter.config(state='disabled' if eb == 1 else 'normal')
        self._cols, self._rows = cols, rows
        cw, ch = max(1, c.winfo_width()), max(1, c.winfo_height())
        gw, gh = len(cols) * z, len(rows) * z
        ox = max(RAND, (cw - gw) // 2)
        oy = max(RAND, (ch - gh) // 2)
        self._ox, self._oy = ox, oy
        # Beschriftung
        for i, col in enumerate(cols):
            c.create_text(ox + i * z + z / 2, oy - RAND / 2, text=col, fill=GOLD, font=('Segoe UI', 10, 'bold'))
        for j, row in enumerate(rows):
            c.create_text(ox - RAND / 2, oy + j * z + z / 2, text=str(row), fill=GOLD, font=('Segoe UI', 10, 'bold'))
        by_pos = {(k.col, k.row): k for k in self.modell.kacheln.values() if k.ebene == eb}
        for i, col in enumerate(cols):
            for j, row in enumerate(rows):
                x, y = ox + i * z, oy + j * z
                k = by_pos.get((col, row))
                if k is None or k.bild() is None:
                    c.create_rectangle(x + 1, y + 1, x + z - 1, y + z - 1, outline=LINE, dash=(3, 3))
                    if z >= 40 and self.zeige_namen.get():
                        c.create_text(x + z / 2, y + z / 2, text=name_von(col, row, eb), fill=DIM, font=FONT_SMALL)
                    continue
                foto = ImageTk.PhotoImage(k.vorschau(z))
                self.fotos[k.name] = foto
                c.create_image(x, y, image=foto, anchor='nw', tags=('kachel', k.name))
                if k.neu is not None:
                    c.create_rectangle(x + 1, y + 1, x + z - 1, y + z - 1, outline=FARBE_NEU, width=2)
                elif k.mod_pfad:
                    c.create_rectangle(x + 1, y + 1, x + z - 1, y + z - 1, outline=FARBE_MOD, width=2)
                if z >= 48 and self.zeige_namen.get():
                    self._schild(x + 3, y + 3, k.name, 7 if z < 96 else 9)
        if self.zeige_linien.get():
            # feine gestrichelte Trennlinien ueber allen Kacheln
            x1, y1 = ox + len(cols) * z, oy + len(rows) * z
            for i in range(len(cols) + 1):
                c.create_line(ox + i * z, oy, ox + i * z, y1, fill=MUT, dash=(2, 4), width=1)
            for j in range(len(rows) + 1):
                c.create_line(ox, oy + j * z, x1, oy + j * z, fill=MUT, dash=(2, 4), width=1)
        if self.tour_ziel:
            zt = zellname(self.tour_ziel)
            if zt and zt[3] == eb and zt[1] in cols and zt[2] in rows:
                i, j = cols.index(zt[1]), rows.index(zt[2])
                x, y = ox + i * z, oy + j * z
                farbe = FARBE_TOUR if getattr(self, 'tour_blink', True) else FARBE_TOUR_2
                c.create_rectangle(x - 3, y - 3, x + z + 3, y + z + 3, outline=farbe, width=7, tags='tourziel')
                t = c.create_text(x + z / 2, y - 14, text=tr('HIER KLICKEN'), fill=FARBE_TEXT_AUF_GOLD, font=('Segoe UI', 10, 'bold'))
                bx0, by0, bx1, by1 = c.bbox(t)
                r = c.create_rectangle(bx0 - 8, by0 - 3, bx1 + 8, by1 + 3, fill=farbe, outline=FARBE_TEXT_AUF_GOLD)
                c.tag_lower(r, t)
        if self.auswahl and self.auswahl.ebene == eb:
            i, j = cols.index(self.auswahl.col), rows.index(self.auswahl.row)
            x, y = ox + i * z, oy + j * z
            c.create_rectangle(x, y, x + z, y + z, outline=FARBE_AUSWAHL, width=3)
        c.configure(scrollregion=(0, 0, max(cw, ox + len(cols) * z + 8), max(ch, oy + len(rows) * z + 8)))
        self.liste_fuellen()
        self.auswahl_anzeigen()

    def _schild(self, x, y, text, groesse):
        """Beschriftung mit dunklem Hintergrund, damit sie auf jedem Pergament lesbar ist."""
        c = self.canvas
        t = c.create_text(x + 3, y + 1, text=text, anchor='nw', fill=INK,
                          font=('Segoe UI', groesse, 'bold'))
        x0, y0, x1, y1 = c.bbox(t)
        r = c.create_rectangle(x0 - 3, y0 - 1, x1 + 3, y1 + 1, fill=PANEL, outline=PANEL)
        c.tag_lower(r, t)

    def liste_fuellen(self):
        self.liste.delete(*self.liste.get_children())
        eb = self.ebene.get()
        ks = sorted((k for k in self.modell.kacheln.values() if k.ebene == eb), key=lambda k: (k.row, k.col))
        for k in ks:
            status = tr('ungespeichert') if k.neu is not None else (tr('geaendert') if k.mod_pfad else '')
            tag = 'neu' if k.neu is not None else ('mod' if k.mod_pfad else '')
            self.liste.insert('', 'end', iid=k.name, values=(k.name, tr(k.quelle), status), tags=(tag,))
        if self.auswahl and self.liste.exists(self.auswahl.name):
            self.liste.selection_set(self.auswahl.name)
            self.liste.see(self.auswahl.name)

    def auswahl_anzeigen(self):
        k = self.auswahl
        self.vorschau.delete('all')
        if k is None:
            self.info.config(text='-')
            self._vorschau_foto = None
            return
        b = k.bild()
        zeilen = [tr('Zelle: {name}   Ebene: {ebene}', name=k.name, ebene=tr(EBENEN[k.ebene])), tr('Quelle: {quelle}', quelle=tr(k.quelle))]
        if k.retail_roh:
            zeilen.append(f'Retail: {len(k.retail_roh)} B DXT1')
        if k.mod_pfad:
            zeilen.append(f'Mod: {os.path.basename(k.mod_pfad)}')
        if k.neu is not None:
            zeilen.append(tr('ungespeichert - Strg+S schreibt die 4 Stufen'))
        self.info.config(text='\n'.join(zeilen))
        if b is None:
            return
        bild = b.resize((VORSCHAU_PX, VORSCHAU_PX), Image.LANCZOS)
        self._vorschau_foto = ImageTk.PhotoImage(bild)
        self.vorschau.create_image(0, 0, image=self._vorschau_foto, anchor='nw')

    # -- Ereignisse ---------------------------------------------------------

    def klick(self, ev):
        x = self.canvas.canvasx(ev.x) - self._ox
        y = self.canvas.canvasy(ev.y) - self._oy
        if x < 0 or y < 0:
            return
        i, j = int(x // self.zoom), int(y // self.zoom)
        if i >= len(self._cols) or j >= len(self._rows):
            return
        col, row = self._cols[i], self._rows[j]
        eb = self.ebene.get()
        name = name_von(col, row, eb)
        k = self.modell.kacheln.get(name)
        if k is None:
            if messagebox.askyesno(tr('Neues Tile'), tr('{name} hat noch keine Kachel. Jetzt anlegen und ein Bild einlegen?', name=name)):
                self.neues_tile(name)
            return
        self.auswahl = k
        self.zeichnen()
        self.sichtbar_machen(k)

    def liste_auswahl(self, ev=None):
        sel = self.liste.selection()
        if not sel:
            return
        k = self.modell.kacheln.get(sel[0])
        if k is not None and k is not self.auswahl:
            self.auswahl = k
            self.zeichnen()
            self.sichtbar_machen(k)

    def sichtbar_machen(self, k):
        cols, rows = self._cols, self._rows
        z = self.zoom
        x = self._ox + cols.index(k.col) * z
        y = self._oy + rows.index(k.row) * z
        sr = self.canvas.cget('scrollregion').split()
        w, h = float(sr[2]), float(sr[3])
        self.canvas.xview_moveto(max(0, (x - self.canvas.winfo_width() / 2 + z / 2) / w))
        self.canvas.yview_moveto(max(0, (y - self.canvas.winfo_height() / 2 + z / 2) / h))

    def suchen(self):
        z = zellname(self.suchtext.get())
        if not z:
            self.melden(tr('Kein Zellname: "{text}" (z. B. E06, e6, F01_1)', text=self.suchtext.get()))
            return
        name, col, row, eb = z
        k = self.modell.kacheln.get(name)
        if k is None:
            if messagebox.askyesno(tr('Nicht vorhanden'), tr('{name} gibt es noch nicht. Neues Tile anlegen?', name=name)):
                self.neues_tile(name)
            return
        self.auswahl = k
        self.ebene.set(eb)
        self.zeichnen()
        self.sichtbar_machen(k)
        self.melden(f'{name}: {tr(k.quelle)}')

    # -- Aktionen -----------------------------------------------------------

    def bild_einlegen(self, kachel=None):
        k = kachel or self.auswahl
        if k is None:
            self.melden(tr('Erst eine Kachel anklicken.'))
            return
        pfad = filedialog.askopenfilename(title=tr('Bild fuer {name} (mind. 512 px)', name=k.name), filetypes=bildtypen())
        if not pfad:
            return
        try:
            im = bild_einpassen(pfad)
        except Exception as ex:
            messagebox.showerror(tr('Bild unbrauchbar'), str(ex))
            return
        w, h = Image.open(pfad).size
        k.neu = im
        k._cache.clear()
        self.auswahl = k
        self.ebene.set(k.ebene)
        self.zeichnen()
        hinweis = '' if w == h else tr(' (mittig quadratisch beschnitten)')
        self.melden(tr('{name}: {datei} {w}x{h}{hinweis} eingelegt - ungespeichert', name=k.name, datei=os.path.basename(pfad), w=w, h=h, hinweis=hinweis))

    def neues_tile(self, vorgabe=None):
        name = vorgabe
        if name is None:
            eb = self.ebene.get()
            text = simpledialog.askstring(tr('Neues Tile'), tr('Zellname (z. B. C13, J9, F05_1):\nReihen 1-9 bekommen eine fuehrende Null, Untergrund das Suffix _1.'),
                                          initialvalue='_1' if eb else '', parent=self)
            if not text:
                return
            z = zellname(text)
            if not z:
                messagebox.showerror(tr('Zellname'), tr('"{text}" ist kein Zellname. Muster: Buchstabe + Zahl, optional _1.', text=text))
                return
            name = z[0]
        z = zellname(name)
        k = self.modell.kacheln.get(name)
        if k is not None and k.bild() is not None:
            if not messagebox.askyesno(tr('Vorhanden'), tr('{name} gibt es schon ({quelle}). Bild ersetzen?', name=name, quelle=tr(k.quelle))):
                return
        else:
            k = self.modell.kachel(*z)
        self.bild_einlegen(k)
        if k.neu is None and k.bild() is None:
            self.modell.kacheln.pop(name, None)   # abgebrochen: leere Kachel weg
            self.zeichnen()

    def exportieren(self):
        k = self.auswahl
        if k is None or k.bild() is None:
            self.melden(tr('Erst eine Kachel anklicken.'))
            return
        pfad = filedialog.asksaveasfilename(title=tr('{name} exportieren', name=k.name), initialfile=f'Map_{k.name}.png',
                                            defaultextension='.png',
                                            filetypes=[('PNG', '*.png'), ('JPEG', '*.jpg'), ('DDS (DXT1, 512)', '*.dds')])
        if not pfad:
            return
        self._bild_speichern(k.bild(), pfad)
        self.melden(tr('{name} exportiert: {pfad}', name=k.name, pfad=pfad))

    def ebene_exportieren(self):
        eb = self.ebene.get()
        pfad = filedialog.asksaveasfilename(title=tr('{ebene} als ein Bild exportieren', ebene=tr(EBENEN[eb])),
                                            initialfile=tr('Weltkarte') + f'_{tr(EBENEN[eb])}.png', defaultextension='.png',
                                            filetypes=[('PNG', '*.png'), ('JPEG', '*.jpg')])
        if not pfad:
            return
        self.melden(tr('Baue die Ebene zusammen ...'))
        big = self.modell.ebene_bild(eb)
        self._bild_speichern(big, pfad)
        self.melden(tr('{ebene} exportiert: {pfad} ({w}x{h} px, 512 px je Kachel)', ebene=tr(EBENEN[eb]), pfad=pfad, w=big.size[0], h=big.size[1]))

    def _bild_speichern(self, bild, pfad):
        ext = os.path.splitext(pfad)[1].lower()
        try:
            if ext == '.dds':
                with open(pfad, 'wb') as f:
                    f.write(dds_schreiben(bild))
            elif ext in ('.jpg', '.jpeg'):
                bild.save(pfad, quality=95)
            else:
                bild.save(pfad)
        except Exception as ex:
            messagebox.showerror(tr('Export fehlgeschlagen'), str(ex))

    def speichern(self):
        ks = self.modell.geaendert()
        if not ks:
            self.melden(tr('Nichts zu speichern.'))
            return
        fehler = []
        for k in ks:
            try:
                self.modell.speichern(k)
            except Exception as ex:
                fehler.append(f'{k.name}: {ex}')
        self.zeichnen()
        if fehler:
            messagebox.showerror(tr('Speichern'), '\n'.join(fehler))
        else:
            self.melden(tr('{n} Kachel(n) als 4 Stufen nach {pfad} geschrieben (Groessen geprueft: 131200/32896/8320/2176 B)', n=len(ks), pfad=self.modell.ausgabe), 'ok')

    def ins_spiel(self):
        if self.modell.geaendert():
            self.speichern()
            if self.modell.geaendert():
                return                      # Speichern hat Fehler gemeldet
        try:
            n = len(self.modell.mod_dateien())
        except Exception as ex:
            messagebox.showerror(tr('Ausgabeordner'), str(ex))
            return
        if not n:
            self.melden(tr('Keine DDS im Ausgabeordner - nichts zu uebernehmen.'))
            return
        laeuft = self.modell.spiel_laeuft()
        text = tr('{n} Dateien ({k} Kacheln) werden als Mods\\{mod}.wd gepackt und unter\nHKCU\\...\\TwoWorlds\\Mods eingeschaltet. Retail-Archive bleiben unveraendert;\ndie vorherigen Kacheln liegen in {backup}.', n=n, k=n // 4, mod=MOD_NAME, backup=self.modell.backup)
        if laeuft:
            text += tr('\n\nTwo Worlds laeuft gerade: die neue Karte erscheint erst nach einem Neustart des Spiels.')
        if not messagebox.askokcancel(tr('Ins Spiel uebernehmen'), text):
            return
        self.melden(tr('Packe ...'))
        try:
            out, n = self.modell.ins_spiel()
        except Exception as ex:
            messagebox.showerror(tr('Uebernehmen fehlgeschlagen'), str(ex))
            self.melden(tr('Uebernehmen fehlgeschlagen.'), 'err')
            return
        self.melden(tr('im Spiel: {out} ({n} Dateien, aktiviert)', out=out, n=n) + (tr(' - Spiel neu starten') if laeuft else ''), 'ok')

    def backup_oeffnen(self):
        b = self.modell.backup
        os.makedirs(b, exist_ok=True)
        os.startfile(b)

    def wd_packen(self):
        if self.modell.geaendert():
            if not messagebox.askyesno(tr('Ungespeichert'), tr('Es gibt ungespeicherte Kacheln. Erst speichern?')):
                return
            self.speichern()
        try:
            dateien = self.modell.mod_dateien()
        except Exception as ex:
            messagebox.showerror(tr('Ausgabeordner'), str(ex))
            return
        if not dateien:
            self.melden(tr('Keine DDS im Ausgabeordner - nichts zu packen.'))
            return
        name = simpledialog.askstring(tr('Mod-Archiv'), tr('{n} Dateien. Name des Archivs (ohne .wd):', n=len(dateien)),
                                      initialvalue='Minimap', parent=self)
        if not name:
            return
        ziel = filedialog.askdirectory(title=tr('Wohin mit der .wd?'), initialdir=MODS_DIR if os.path.isdir(MODS_DIR) else HERE)
        if not ziel:
            return
        try:
            import packer
            out = packer.pack_mod(ziel, name, dateien)
        except Exception as ex:
            messagebox.showerror(tr('Packen fehlgeschlagen'), str(ex))
            return
        self.melden(tr('gepackt: {out} - im Mod-Manager bzw. unter HKCU\\...\\TwoWorlds\\Mods aktivieren', out=out))
        messagebox.showinfo(tr('Mod-Archiv'), tr('{out}\n\n{n} Dateien unter Levels\\MipMaps\\.\nZum Aktivieren die .wd in Mods\\ legen und im Mod-Manager einschalten.', out=out, n=len(dateien)))

    def ausgabe_waehlen(self):
        d = filedialog.askdirectory(title=tr('Ausgabeordner fuer Map_<Zelle>@0..3.dds'), initialdir=self.modell.ausgabe)
        if not d:
            return
        if self.modell.geaendert() and not messagebox.askyesno(tr('Ungespeichert'), tr('Ungespeicherte Kacheln verwerfen und Ordner wechseln?')):
            return
        self.modell.ausgabe = d
        for k in self.modell.kacheln.values():
            k.neu = None
        self.modell.mod_dateien_lesen()
        self.zeichnen()
        self.melden(tr('Ausgabeordner: {pfad}', pfad=d))

    def verwerfen(self):
        k = self.auswahl
        if k is None or k.neu is None:
            self.melden(tr('Keine ungespeicherte Aenderung an dieser Kachel.'))
            return
        k.neu = None
        k._cache.clear()
        if k.bild() is None:
            self.modell.kacheln.pop(k.name, None)
            self.auswahl = None
        self.zeichnen()

    def alle_verwerfen(self):
        ks = self.modell.geaendert()
        if not ks:
            return
        if not messagebox.askyesno(tr('Verwerfen'), tr('{n} ungespeicherte Kachel(n) verwerfen?', n=len(ks))):
            return
        for k in ks:
            k.neu = None
            k._cache.clear()
            if k.bild() is None:
                self.modell.kacheln.pop(k.name, None)
        self.auswahl = None
        self.zeichnen()

    def retail_zurueck(self):
        k = self.auswahl
        if k is None:
            return
        if not k.mod_pfad and k.neu is None:
            self.melden(tr('{name} ist schon Retail.', name=k.name))
            return
        if not messagebox.askyesno(tr('Retail zurueck'), tr('{name}: Mod-Dateien aus dem Ausgabeordner nehmen (Kopie bleibt im backup\\) und die Retail-Kachel zeigen?\nDanach "Ins Spiel uebernehmen", damit auch das Spiel sie wieder zeigt.', name=k.name)):
            return
        self.modell.retail_wiederherstellen(k)
        if k.name not in self.modell.kacheln:
            self.auswahl = None
        self.zeichnen()

    def anleitung(self):
        messagebox.showinfo(tr('Kurzanleitung'), tr(KURZANLEITUNG))

    def beenden(self):
        ks = self.modell.geaendert()
        if ks and not messagebox.askyesno(tr('Beenden'), tr('{n} ungespeicherte Kachel(n) verwerfen und beenden?', n=len(ks))):
            return
        self.destroy()

    def sprache_wechseln(self):
        neu = self.sprache_var.get()
        einstellungen_schreiben(sprache=neu)
        if neu != SPRACHE:
            messagebox.showinfo('Language / Sprache',
                                'The language changes after a restart of the tool.\n'
                                'Die Sprache wechselt nach einem Neustart des Werkzeugs.')

    # -- Einfuehrung (Schritt fuer Schritt, zum Mitmachen) --------------------

    def tour_starten(self):
        if getattr(self, 'tour', None) is not None and self.tour.winfo_exists():
            self.tour.lift()
            return
        self.tour = Tour(self)


# ---------------------------------------------------------------------------
#  Einstellungen (Tour gesehen, Ansicht)
# ---------------------------------------------------------------------------

EINSTELLUNGEN = os.path.join(DATEN, 'minimap_tool_settings.json')


def einstellungen_lesen():
    try:
        import json
        with open(EINSTELLUNGEN, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def einstellungen_schreiben(**werte):
    import json
    e = einstellungen_lesen()
    e.update(werte)
    try:
        os.makedirs(DATEN, exist_ok=True)
        with open(EINSTELLUNGEN, 'w', encoding='utf-8') as f:
            json.dump(e, f, indent=1)
    except OSError:
        pass


# ---------------------------------------------------------------------------
#  Tour
# ---------------------------------------------------------------------------

TOUR_TAUSCH = 'E06'      # Retail-Kachel, die in der Einfuehrung getauscht wird
TOUR_NEU = 'Z05'         # leeres Feld links neben der Karte fuer die neue Kachel


class Tour(tk.Toplevel):
    """Schritt-fuer-Schritt-Einfuehrung zum Mitmachen.

    Jeder Schritt wartet, bis der Nutzer die Aktion im Hauptfenster gemacht
    hat (Pruefung alle 400 ms), und schaltet dann 'Weiter' frei. Am Ende ist
    der Ausgabeordner wieder wie vorher; die Sicherungen bleiben in backup\\.
    """

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title(tr('Einfuehrung'))
        self.configure(background=BG)
        theme.dark_titlebar(self)
        self.resizable(False, False)
        self.attributes('-topmost', True)
        self.protocol('WM_DELETE_WINDOW', self.schliessen)
        self.beispiel = os.path.join(app.modell.ausgabe, 'tour_beispiel.png')
        self.schritt = 0
        self.job = None
        self.schritte = self._schritte()

        f = ttk.Frame(self, padding=16)
        f.pack(fill='both', expand=True)
        self.kopf = ttk.Label(f, text='', font=('Segoe UI Semibold', 11), foreground=GOLD)
        self.kopf.pack(anchor='w')
        self.text = ttk.Label(f, text='', wraplength=420, justify='left')
        self.text.pack(anchor='w', pady=(6, 8))
        self.zustand = ttk.Label(f, text='', style='Muted.TLabel')
        self.zustand.pack(anchor='w')
        self.extra = ttk.Button(f, text='', command=self._extra)
        kn = ttk.Frame(f)
        kn.pack(fill='x', pady=(12, 0))
        self.fortschritt = ttk.Label(kn, text='', foreground=GOLD, font=FONT_BOLD)
        self.fortschritt.pack(side='left')
        self.nicht_mehr = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text=tr('Beim Start nicht mehr anzeigen'), variable=self.nicht_mehr).pack(anchor='w', pady=(8, 0))
        ttk.Button(kn, text=tr('Abbrechen'), command=self.schliessen).pack(side='right')
        self.weiter = ttk.Button(kn, text=tr('Weiter'), command=self.naechster, style='Accent.TButton')
        self.weiter.pack(side='right', padx=(0, 6))
        self.zurueck = ttk.Button(kn, text=tr('Zurueck'), command=self.voriger)
        self.zurueck.pack(side='right', padx=(0, 6))

        self.update_idletasks()
        self.platzieren()
        self.zeigen()

    def platzieren(self):
        # oben links im Kartenbereich, unter der Werkzeugleiste - dort ist bei
        # zentrierter Karte Platz, und nichts vom Fenster ragt aus dem Bild
        app = self.app
        x = app.canvas.winfo_rootx() + 24
        y = app.canvas.winfo_rooty() + 24
        self.geometry(f'+{max(0, x)}+{max(0, y)}')

    # -- Schritte -----------------------------------------------------------

    def _k(self, name):
        return self.app.modell.kacheln.get(name)

    def _schritte(self):
        A, T, N = self.app, TOUR_TAUSCH, TOUR_NEU
        return [
            dict(titel=tr('Willkommen'), text=tr(TOUR_T['willkommen']), ziel=None, pruefen=None),
            dict(titel=tr('1. Kachel {T} anklicken', T=T), text=tr(TOUR_T['anklicken'], T=T),
                 ziel=T, pruefen=lambda: A.auswahl is not None and A.auswahl.name == T),
            dict(titel=tr('2. Bild einlegen'), knoepfe=['bild_einlegen'],
                 text=tr(TOUR_T['einlegen'], beispiel=self.beispiel),
                 ziel=T, pruefen=lambda: self._k(T) is not None and self._k(T).neu is not None,
                 extra=tr('Beispielbild direkt einlegen'), extra_cmd=lambda: self._beispiel_einlegen(T)),
            dict(titel=tr('3. Speichern'), knoepfe=['speichern'], text=tr(TOUR_T['speichern'], T=T),
                 ziel=T, pruefen=lambda: self._k(T) is not None and self._k(T).neu is None and bool(self._k(T).mod_pfad)),
            dict(titel=tr('Ins Spiel'), knoepfe=['ins_spiel'], text=tr(TOUR_T['ins_spiel']),
                 ziel=T, pruefen=None),
            dict(titel=tr('4. Zuruecksetzen'), knoepfe=['retail_zurueck'], text=tr(TOUR_T['zuruecksetzen'], T=T),
                 ziel=T, pruefen=lambda: self._k(T) is not None and self._k(T).quelle == 'Retail'),
            dict(titel=tr('5. Neue Kachel {N} anlegen', N=N), text=tr(TOUR_T['neu'], N=N),
                 ziel=N, pruefen=lambda: self._k(N) is not None and self._k(N).bild() is not None,
                 extra=tr('Beispielbild direkt einlegen'), extra_cmd=lambda: self._beispiel_neu(N)),
            dict(titel=tr('6. Speichern'), knoepfe=['speichern'], text=tr(TOUR_T['neu_speichern'], N=N),
                 ziel=N, pruefen=lambda: self._k(N) is not None and self._k(N).neu is None and bool(self._k(N).mod_pfad)),
            dict(titel=tr('7. Wieder entfernen'), knoepfe=['retail_zurueck'], text=tr(TOUR_T['entfernen'], N=N),
                 ziel=N, pruefen=lambda: self._k(N) is None),
            dict(titel=tr('Fertig'), text=tr(TOUR_T['fertig']), ziel=None, pruefen=None),
        ]

    # -- Ablauf ---------------------------------------------------------------

    def zeigen(self):
        s = self.schritte[self.schritt]
        self.kopf.config(text=s['titel'])
        self.text.config(text=s['text'])
        self.fortschritt.config(text=tr('Schritt {i} von {n}', i=self.schritt + 1, n=len(self.schritte)))
        self.zurueck.config(state='normal' if self.schritt > 0 else 'disabled')
        self.weiter.config(text=tr('Beenden') if self.schritt == len(self.schritte) - 1 else tr('Weiter'))
        if s.get('extra'):
            self.extra.config(text=s['extra'])
            self.extra.pack(anchor='w', pady=(0, 4))
        else:
            self.extra.pack_forget()
        self.app.tour_ziel = s['ziel']
        self._marker_setzen(s.get('knoepfe', []))
        if s['ziel']:
            z = zellname(s['ziel'])
            if z and self.app.ebene.get() != z[3]:
                self.app.ebene.set(z[3])
        self.app.zeichnen()
        self.pruefen()

    def _marker_setzen(self, namen):
        """Gruene Pfeil-Marker direkt vor jeden Knopf, der jetzt dran ist."""
        for m in getattr(self, 'marker', []):
            m.destroy()
        self.marker = []
        for name in namen:
            for b in self.app.knoepfe.get(name, []):
                m = tk.Label(b.master, text=tr('▶ HIER'), background=FARBE_TOUR, foreground=FARBE_TEXT_AUF_GOLD,
                             font=FONT_BOLD, padx=4)
                m.pack(side='left', before=b, padx=(6, 0))
                self.marker.append(m)
        if getattr(self, 'blink_job', None) is None:
            self._blinken()

    def _blinken(self):
        self.app.tour_blink = not getattr(self.app, 'tour_blink', True)
        farbe = FARBE_TOUR if self.app.tour_blink else FARBE_TOUR_2
        for m in self.marker:
            m.config(background=farbe)
        c = self.app.canvas
        for item in c.find_withtag('tourziel'):
            c.itemconfigure(item, outline=farbe)
        self.blink_job = self.after(550, self._blinken)

    def pruefen(self):
        if self.job:
            self.after_cancel(self.job)
            self.job = None
        s = self.schritte[self.schritt]
        if s['pruefen'] is None:
            self.zustand.config(text='', foreground=MUT)
            self.weiter.config(state='normal')
            return
        try:
            ok = bool(s['pruefen']())
        except Exception:
            ok = False
        self.zustand.config(text=tr('Erledigt - weiter geht es mit "Weiter".') if ok else tr('Warte auf deine Aktion im Hauptfenster ...'),
                            foreground=OK if ok else MUT)
        self.weiter.config(state='normal' if ok else 'disabled')
        if not ok:
            self.job = self.after(400, self.pruefen)

    def naechster(self):
        if self.schritt >= len(self.schritte) - 1:
            self.schliessen(fertig=True)
            return
        self.schritt += 1
        self.zeigen()

    def voriger(self):
        if self.schritt > 0:
            self.schritt -= 1
            self.zeigen()

    def _extra(self):
        s = self.schritte[self.schritt]
        if s.get('extra_cmd'):
            s['extra_cmd']()

    def _beispiel_sicherstellen(self):
        """Beispielbild: die Retail-Kachel E06 blau eingefaerbt und beschriftet."""
        if os.path.exists(self.beispiel):
            return
        k = self._k(TOUR_TAUSCH)
        basis = k.retail() if k and k.retail() else Image.new('RGB', (512, 512), (180, 150, 100))
        from PIL import ImageOps, ImageDraw
        b = ImageOps.colorize(ImageOps.grayscale(basis), (20, 40, 90), (200, 220, 255))
        d = ImageDraw.Draw(b)
        d.rectangle((16, 16, 495, 495), outline=(255, 255, 255), width=6)
        d.text((40, 40), 'TOUR-BEISPIEL', fill=(255, 255, 255))
        os.makedirs(os.path.dirname(self.beispiel), exist_ok=True)
        b.save(self.beispiel)

    def _beispiel_einlegen(self, name):
        self._beispiel_sicherstellen()
        k = self._k(name)
        if k is None:
            return
        k.neu = bild_einpassen(self.beispiel)
        k._cache.clear()
        self.app.auswahl = k
        self.app.zeichnen()
        self.app.melden(tr('{name}: Beispielbild eingelegt - ungespeichert', name=name))

    def _beispiel_neu(self, name):
        self._beispiel_sicherstellen()
        z = zellname(name)
        k = self.app.modell.kachel(*z)
        self._beispiel_einlegen(name)
        self.app.ebene.set(k.ebene)
        self.app.zeichnen()

    def schliessen(self, fertig=False):
        if self.job:
            self.after_cancel(self.job)
        if getattr(self, 'blink_job', None):
            self.after_cancel(self.blink_job)
            self.blink_job = None
        for m in getattr(self, 'marker', []):
            m.destroy()
        self.marker = []
        self.app.tour_ziel = None
        self.app.tour = None
        # gemerkt wird nur, wenn der Haken sitzt oder der letzte Schritt erreicht war
        if fertig or self.nicht_mehr.get() or self.schritt >= len(self.schritte) - 1:
            einstellungen_schreiben(tour_gesehen=True)
        if fertig:
            self.app.melden(tr('Einfuehrung abgeschlossen - jederzeit unter Hilfe > Einfuehrung.'))
        self.app.zeichnen()
        self.destroy()


# ---------------------------------------------------------------------------
#  Texte
# ---------------------------------------------------------------------------

KURZANLEITUNG = (
    'Kachel anklicken, dann "Bild einlegen" (PNG/JPG/BMP/DDS, mind. 512 px).\n'
    'Orange = ungespeichert, Blau = im Ausgabeordner, Rot = Auswahl.\n'
    'Strg+S schreibt je Kachel Map_<Zelle>@0..3.dds (DXT1, 512/256/128/64)\n'
    'in den Ausgabeordner; der vorherige Stand (Retail bzw. alte Mod-Fassung)\n'
    'landet vorher in backup\\.\n'
    'Strg+G / "Ins Spiel uebernehmen" packt den Ausgabeordner als Mods\\Minimap.wd\n'
    'und schaltet die Mod ein - Retail-Archive werden nie veraendert.\n'
    'Der Standard-Ausgabeordner QuestForge\\minimap fliesst auch in build_campaign.py ein.\n\n'
    'Neue Karten: "Neues Tile", Zellname wie der der .lnd (Map_C13.lnd -> C13,\n'
    'Map_F05_1.lnd -> F05_1). Leere Rasterfelder sind direkt anklickbar.\n'
    'Die bestehende Zeichnung nicht verschieben: der Positionspfeil folgt\n'
    'den Weltkoordinaten.')

UEBER_TEXT = ('Zeigt die Minimap-Kacheln von Two Worlds 1 als Weltkarte, tauscht einzelne Kacheln gegen '
              'eigene Bilder, legt Kacheln fuer neue Karten an und packt alles als Mod-Archiv, ohne die '
              'Spieldateien anzufassen.')

TOUR_T = {
    'willkommen':
        'Diese Einfuehrung geht einmal durch alles, was das Werkzeug kann: eine Kachel '
        'tauschen und wieder zuruecksetzen, dann eine neue Kachel anlegen und wieder '
        'entfernen. Am Ende ist alles wie vorher.\n\n'
        'Die Karte links ist aus den Minimap-Kacheln des Spiels gebaut. Mausrad zoomt, '
        'rechte Maustaste zieht, unten rechts wechselst du zwischen Oberflaeche und Unterwelt.',
    'anklicken':
        'Klick auf die gruen umrandete Kachel {T} (Cathalon-Umland). Sie wird rot markiert '
        'und erscheint rechts in voller Aufloesung. Die Suche oben ("e6" reicht) '
        'findet sie ebenfalls.',
    'einlegen':
        'Klick "Bild einlegen" und waehle das Beispielbild:\n{beispiel}\n\n'
        'Jedes PNG/JPG/BMP/DDS ab 512 px geht; groessere Bilder werden skaliert, '
        'nicht quadratische mittig beschnitten. Die Kachel bekommt einen orangen '
        'Rahmen: eingelegt, aber noch nicht gespeichert.',
    'speichern':
        'Strg+S oder "Speichern". Das Werkzeug schreibt die vier DXT1-Stufen '
        'Map_{T}@0..3.dds in den Ausgabeordner und sichert vorher die Retail-Kachel '
        'nach backup\\retail\\. Der Rahmen wird blau: im Ausgabeordner.',
    'ins_spiel':
        'Von hier aus wuerde "Ins Spiel uebernehmen" (Strg+G) den Ausgabeordner als '
        'Mods\\Minimap.wd packen und die Mod einschalten - die Retail-Archive bleiben '
        'unangetastet. In der Einfuehrung lassen wir das aus.',
    'zuruecksetzen':
        'Kachel {T} ist noch markiert. Klick "Retail zurueck" (rechts unten) und '
        'bestaetige. Die getauschte Fassung wandert nach backup\\<Datum>\\, die Kachel '
        'zeigt wieder Retail.',
    'neu':
        'Klick auf das leere Feld {N} links neben der Karte (gruen umrandet) und '
        'bestaetige "anlegen". Waehle im Dateidialog wieder das Beispielbild. '
        'Genauso ginge "Neues Tile" mit Zellname, z. B. fuer eine neue Karte Map_{N}.lnd.',
    'neu_speichern':
        'Strg+S. {N} liegt jetzt als Map_{N}@0..3.dds im Ausgabeordner und wuerde '
        'mit ins Spiel gehen. Wenn dort einmal eine echte Karte Map_{N}.lnd liegt, ist '
        'das ihre Minimap.',
    'entfernen':
        '{N} markieren und "Retail zurueck". Es gibt keine Retail-Kachel dafuer, also '
        'verschwindet das Feld wieder aus der Liste; die Datei liegt im backup\\.',
    'fertig':
        'Das war alles. Merken:\n'
        '- Orange = eingelegt, Blau = gespeichert, Rot = Auswahl, Gruen = Tour-Ziel\n'
        '- Strg+S speichert, Strg+G bringt es ins Spiel (Spiel danach neu starten)\n'
        '- backup\\ haelt jeden ersetzten Stand, "Sicherungsordner oeffnen" im Datei-Menue\n'
        '- Hilfe > Einfuehrung startet diese Tour jederzeit neu',
}

TEXTE_EN = {
    # Fehler
    'Pillow hat kein reines DXT1 geschrieben ({ist} B statt {soll} B)': 'Pillow did not write plain DXT1 ({ist} B instead of {soll} B)',
    'Stufe {s}: {ist} B statt {soll} B': 'Level {s}: {ist} B instead of {soll} B',
    '{datei}: {w}x{h} px - mindestens 512 px je Seite': '{datei}: {w}x{h} px - needs at least 512 px per side',
    '{pfad}: {ist} B statt {soll} B': '{pfad}: {ist} B instead of {soll} B',
    'keine DDS im Ausgabeordner': 'no DDS files in the output folder',
    'Mods-Ordner fehlt: {pfad}': 'Mods folder missing: {pfad}',
    # Allgemein
    'Bilder': 'Images', 'Alle Dateien': 'All files', 'Strg': 'Ctrl', 'Mausrad': 'Mouse wheel',
    'Oberfläche': 'Surface', 'Unterwelt': 'Underworld', 'Retail': 'Retail', 'Mod': 'Mod', 'neu': 'new', '-': '-',
    # Menue
    'Bild einlegen...': 'Insert image...', 'Kachel exportieren...': 'Export tile...',
    'Ganze Ebene exportieren...': 'Export whole layer...', 'Neues Tile...': 'New tile...',
    'Aenderungen speichern': 'Save changes', 'Ins Spiel uebernehmen (Mods\\Minimap.wd)': 'Apply to game (Mods\\Minimap.wd)',
    'Als Mod-Archiv (.wd) woanders packen...': 'Pack as mod archive (.wd) elsewhere...',
    'Sicherungsordner oeffnen': 'Open backup folder', 'Ausgabeordner waehlen...': 'Choose output folder...',
    'Beenden': 'Quit', 'Datei': 'File', 'Aenderung dieser Kachel verwerfen': 'Discard change of this tile',
    'Alle ungespeicherten Aenderungen verwerfen': 'Discard all unsaved changes',
    'Kachel auf Retail zuruecksetzen (Mod-Dateien loeschen)': 'Reset tile to retail (delete mod files)',
    'Bearbeiten': 'Edit', 'Vergroessern': 'Zoom in', 'Verkleinern': 'Zoom out', 'Einpassen': 'Fit',
    'Trennlinien zwischen den Kacheln': 'Grid lines between tiles', 'Kachelnamen': 'Tile names', 'Neu laden': 'Reload',
    'Ansicht': 'View', 'Einfuehrung (Schritt fuer Schritt)...': 'Guided tour (step by step)...',
    'Kurzanleitung': 'Quick guide', 'Hilfe': 'Help',
    # Werkzeugleiste / Seite
    'Suche:': 'Search:', 'Gehe zu': 'Go to', 'Neues Tile': 'New tile', 'Bild einlegen': 'Insert image',
    'Exportieren': 'Export', 'Speichern': 'Save', 'Ins Spiel uebernehmen': 'Apply to game',
    'Linien': 'Lines', 'Namen': 'Names', 'Kacheln dieser Ebene': 'Tiles of this layer',
    'Zelle': 'Cell', 'Quelle': 'Source', 'Status': 'Status', 'Ausgewaehlte Kachel': 'Selected tile',
    'Vorschau der Kachel (512 px, verkleinert)': 'Tile preview (512 px, scaled down)',
    'Exportieren...': 'Export...', 'Verwerfen': 'Discard', 'Retail zurueck': 'Back to retail',
    # Meldungen
    'Ungespeicherte Aenderungen gehen verloren. Trotzdem neu laden?': 'Unsaved changes will be lost. Reload anyway?',
    'Levels.wd fehlt': 'Levels.wd missing', 'Nicht gefunden:\n{pfad}': 'Not found:\n{pfad}',
    'Lade Levels.wd ...': 'Loading Levels.wd ...', 'Laden fehlgeschlagen': 'Loading failed',
    '{n_ob} Kacheln Oberfläche, {n_un} Unterwelt - Ausgabe: {pfad}': '{n_ob} surface tiles, {n_un} underworld - output: {pfad}',
    'HIER KLICKEN': 'CLICK HERE', 'ungespeichert': 'unsaved', 'geaendert': 'changed',
    'Zelle: {name}   Ebene: {ebene}': 'Cell: {name}   Layer: {ebene}', 'Quelle: {quelle}': 'Source: {quelle}',
    'ungespeichert - Strg+S schreibt die 4 Stufen': 'unsaved - Ctrl+S writes the 4 levels',
    '{name} hat noch keine Kachel. Jetzt anlegen und ein Bild einlegen?': '{name} has no tile yet. Create it now and insert an image?',
    'Kein Zellname: "{text}" (z. B. E06, e6, F01_1)': 'Not a cell name: "{text}" (e.g. E06, e6, F01_1)',
    'Nicht vorhanden': 'Not present', '{name} gibt es noch nicht. Neues Tile anlegen?': '{name} does not exist yet. Create a new tile?',
    'Erst eine Kachel anklicken.': 'Click a tile first.', 'Bild fuer {name} (mind. 512 px)': 'Image for {name} (at least 512 px)',
    'Bild unbrauchbar': 'Image unusable', ' (mittig quadratisch beschnitten)': ' (center-cropped to square)',
    '{name}: {datei} {w}x{h}{hinweis} eingelegt - ungespeichert': '{name}: {datei} {w}x{h}{hinweis} inserted - unsaved',
    'Zellname (z. B. C13, J9, F05_1):\nReihen 1-9 bekommen eine fuehrende Null, Untergrund das Suffix _1.':
        'Cell name (e.g. C13, J9, F05_1):\nRows 1-9 get a leading zero, underworld the suffix _1.',
    'Zellname': 'Cell name', '"{text}" ist kein Zellname. Muster: Buchstabe + Zahl, optional _1.': '"{text}" is not a cell name. Pattern: letter + number, optional _1.',
    'Vorhanden': 'Exists', '{name} gibt es schon ({quelle}). Bild ersetzen?': '{name} already exists ({quelle}). Replace the image?',
    '{name} exportieren': 'Export {name}', '{name} exportiert: {pfad}': '{name} exported: {pfad}',
    '{ebene} als ein Bild exportieren': 'Export {ebene} as one image', 'Weltkarte': 'Worldmap',
    'Baue die Ebene zusammen ...': 'Assembling the layer ...',
    '{ebene} exportiert: {pfad} ({w}x{h} px, 512 px je Kachel)': '{ebene} exported: {pfad} ({w}x{h} px, 512 px per tile)',
    'Export fehlgeschlagen': 'Export failed', 'Nichts zu speichern.': 'Nothing to save.',
    '{n} Kachel(n) als 4 Stufen nach {pfad} geschrieben (Groessen geprueft: 131200/32896/8320/2176 B)':
        '{n} tile(s) written as 4 levels to {pfad} (sizes verified: 131200/32896/8320/2176 B)',
    'Ausgabeordner': 'Output folder', 'Keine DDS im Ausgabeordner - nichts zu uebernehmen.': 'No DDS in the output folder - nothing to apply.',
    '{n} Dateien ({k} Kacheln) werden als Mods\\{mod}.wd gepackt und unter\nHKCU\\...\\TwoWorlds\\Mods eingeschaltet. Retail-Archive bleiben unveraendert;\ndie vorherigen Kacheln liegen in {backup}.':
        '{n} files ({k} tiles) will be packed as Mods\\{mod}.wd and enabled under\nHKCU\\...\\TwoWorlds\\Mods. Retail archives stay untouched;\nthe previous tiles are kept in {backup}.',
    '\n\nTwo Worlds laeuft gerade: die neue Karte erscheint erst nach einem Neustart des Spiels.': '\n\nTwo Worlds is running: the new map appears only after restarting the game.',
    'Packe ...': 'Packing ...', 'Uebernehmen fehlgeschlagen': 'Apply failed', 'Uebernehmen fehlgeschlagen.': 'Apply failed.',
    'im Spiel: {out} ({n} Dateien, aktiviert)': 'in game: {out} ({n} files, enabled)', ' - Spiel neu starten': ' - restart the game',
    'Ungespeichert': 'Unsaved', 'Es gibt ungespeicherte Kacheln. Erst speichern?': 'There are unsaved tiles. Save first?',
    'Keine DDS im Ausgabeordner - nichts zu packen.': 'No DDS in the output folder - nothing to pack.',
    'Mod-Archiv': 'Mod archive', '{n} Dateien. Name des Archivs (ohne .wd):': '{n} files. Name of the archive (without .wd):',
    'Wohin mit der .wd?': 'Where to put the .wd?', 'Packen fehlgeschlagen': 'Packing failed',
    'gepackt: {out} - im Mod-Manager bzw. unter HKCU\\...\\TwoWorlds\\Mods aktivieren': 'packed: {out} - enable it in the mod manager or under HKCU\\...\\TwoWorlds\\Mods',
    '{out}\n\n{n} Dateien unter Levels\\MipMaps\\.\nZum Aktivieren die .wd in Mods\\ legen und im Mod-Manager einschalten.':
        '{out}\n\n{n} files under Levels\\MipMaps\\.\nTo enable, put the .wd into Mods\\ and switch it on in the mod manager.',
    'Ausgabeordner fuer Map_<Zelle>@0..3.dds': 'Output folder for Map_<cell>@0..3.dds',
    'Ungespeicherte Kacheln verwerfen und Ordner wechseln?': 'Discard unsaved tiles and switch folder?',
    'Ausgabeordner: {pfad}': 'Output folder: {pfad}', 'Keine ungespeicherte Aenderung an dieser Kachel.': 'No unsaved change on this tile.',
    '{n} ungespeicherte Kachel(n) verwerfen?': 'Discard {n} unsaved tile(s)?', '{name} ist schon Retail.': '{name} is already retail.',
    '{name}: Mod-Dateien aus dem Ausgabeordner nehmen (Kopie bleibt im backup\\) und die Retail-Kachel zeigen?\nDanach "Ins Spiel uebernehmen", damit auch das Spiel sie wieder zeigt.':
        '{name}: remove the mod files from the output folder (a copy stays in backup\\) and show the retail tile?\nAfterwards "Apply to game" so the game shows it again too.',
    '{n} ungespeicherte Kachel(n) verwerfen und beenden?': 'Discard {n} unsaved tile(s) and quit?',
    # Hilfe / Ueber
    'Ueber': 'About', 'Version {v}': 'Version {v}', 'Schliessen': 'Close',
    'GitHub-Repo': 'GitHub repo', 'Alchemy Fox': 'Alchemy Fox', 'Guide-Seite': 'Guide page', 'Community': 'Community',
    'Beim Start nicht mehr anzeigen': "Don't show at startup",
    'Minimap-Kacheln aus Two Worlds 1 (Reality Pump, 2007). Packen ueber wdio von buglord.':
        'Minimap tiles from Two Worlds 1 (Reality Pump, 2007). Packing via wdio by buglord.',
    UEBER_TEXT:
        'Shows the minimap tiles of Two Worlds 1 as a world map, swaps single tiles for your own images, '
        'creates tiles for new maps and packs everything as a mod archive without touching the game files.',
    # Tour
    'Einfuehrung': 'Guided tour', 'Abbrechen': 'Cancel', 'Weiter': 'Next', 'Zurueck': 'Back',
    'Schritt {i} von {n}': 'Step {i} of {n}', '▶ HIER': '▶ HERE',
    'Erledigt - weiter geht es mit "Weiter".': 'Done - continue with "Next".',
    'Warte auf deine Aktion im Hauptfenster ...': 'Waiting for your action in the main window ...',
    '{name}: Beispielbild eingelegt - ungespeichert': '{name}: sample image inserted - unsaved',
    'Einfuehrung abgeschlossen - jederzeit unter Hilfe > Einfuehrung.': 'Tour finished - available any time under Help > Guided tour.',
    'Willkommen': 'Welcome', '1. Kachel {T} anklicken': '1. Click tile {T}', '2. Bild einlegen': '2. Insert image',
    'Beispielbild direkt einlegen': 'Insert sample image directly', '3. Speichern': '3. Save', 'Ins Spiel': 'Into the game',
    '4. Zuruecksetzen': '4. Reset', '5. Neue Kachel {N} anlegen': '5. Create new tile {N}', '6. Speichern': '6. Save',
    '7. Wieder entfernen': '7. Remove again', 'Fertig': 'Done',
    TOUR_T['willkommen']:
        'This tour walks through everything the tool does: swap a tile and reset it, then create a '
        'new tile and remove it again. In the end everything is as before.\n\n'
        'The map on the left is built from the game\'s minimap tiles. The mouse wheel zooms, the right '
        'mouse button pans, bottom right switches between surface and underworld.',
    TOUR_T['anklicken']:
        'Click the green-framed tile {T} (Cathalon surroundings). It turns red and appears on the '
        'right in full resolution. The search box at the top ("e6" is enough) finds it as well.',
    TOUR_T['einlegen']:
        'Click "Insert image" and choose the sample image:\n{beispiel}\n\n'
        'Any PNG/JPG/BMP/DDS of 512 px or more works; larger images are scaled, non-square ones '
        'center-cropped. The tile gets an orange frame: inserted, but not saved yet.',
    TOUR_T['speichern']:
        'Ctrl+S or "Save". The tool writes the four DXT1 levels Map_{T}@0..3.dds into the output '
        'folder and first backs up the retail tile to backup\\retail\\. The frame turns blue: in the output folder.',
    TOUR_T['ins_spiel']:
        'From here, "Apply to game" (Ctrl+G) would pack the output folder as Mods\\Minimap.wd and '
        'enable the mod - the retail archives stay untouched. We skip that in the tour.',
    TOUR_T['zuruecksetzen']:
        'Tile {T} is still selected. Click "Back to retail" (bottom right) and confirm. The swapped '
        'version moves to backup\\<date>\\, the tile shows retail again.',
    TOUR_T['neu']:
        'Click the empty field {N} left of the map (green frame) and confirm "create". Choose the '
        'sample image again in the file dialog. "New tile" with a cell name works the same way, '
        'e.g. for a new map Map_{N}.lnd.',
    TOUR_T['neu_speichern']:
        'Ctrl+S. {N} now sits as Map_{N}@0..3.dds in the output folder and would go into the game. '
        'Once a real map Map_{N}.lnd exists there, this is its minimap.',
    TOUR_T['entfernen']:
        'Select {N} and click "Back to retail". There is no retail tile for it, so the field '
        'disappears from the list again; the file stays in backup\\.',
    TOUR_T['fertig']:
        'That was all. Remember:\n'
        '- Orange = inserted, Blue = saved, Red = selection, Green = tour target\n'
        '- Ctrl+S saves, Ctrl+G applies to the game (restart the game afterwards)\n'
        '- backup\\ keeps every replaced state, "Open backup folder" in the File menu\n'
        '- Help > Guided tour restarts this tour any time',
    KURZANLEITUNG:
        'Click a tile, then "Insert image" (PNG/JPG/BMP/DDS, at least 512 px).\n'
        'Orange = unsaved, Blue = in the output folder, Red = selection.\n'
        'Ctrl+S writes Map_<cell>@0..3.dds per tile (DXT1, 512/256/128/64)\n'
        'into the output folder; the previous state (retail or old mod version)\n'
        'goes to backup\\ first.\n'
        'Ctrl+G / "Apply to game" packs the output folder as Mods\\Minimap.wd\n'
        'and enables the mod - retail archives are never changed.\n'
        'The default output folder QuestForge\\minimap also feeds build_campaign.py.\n\n'
        'New maps: "New tile", cell name like the .lnd (Map_C13.lnd -> C13,\n'
        'Map_F05_1.lnd -> F05_1). Empty grid fields are clickable directly.\n'
        'Do not move the existing drawing: the position arrow follows\n'
        'world coordinates.',
}


if __name__ == '__main__':
    App().mainloop()
