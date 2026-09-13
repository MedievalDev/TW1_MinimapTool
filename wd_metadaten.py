"""Verzeichniseintraege einer Mod gegen die ausgelieferten Archive angleichen.

Eine .wd traegt zu jeder Datei mehr als nur den Pfad: ein Flag-Byte und je
nach Flag einen Ressourcennamen, eine Klassen-Id und eine GUID. Diese Felder
stehen NICHT im Dateikoerper, sondern nur im Verzeichnis des Archivs.

Beim Neupacken gehen sie still verloren, sobald die gestagte Datei ihren
Kopfsatz-Strom nicht mehr traegt: wdio.v1_chk_file sieht dann kein 78 9c am
Dateianfang und vergibt flags=0x01. Das Spiel startet trotzdem, laedt die
Datei auch - ordnet sie aber nichts mehr zu. Genau das hat PQuests.eco
lahmgelegt (Test1 bis Test4: Skript byte-identisch, trotzdem keine Quest).

Gemessen am 18.08.2026 ueber alle 19 ausgelieferten Archive, 23 703
Eintraege: Flags, Name und Klassen-Id sind je Pfad ueber alle Archive
identisch - einzige Ausnahme EditorDef.txt (0x01 bzw. 0x05, harmloses
Textflag). Die GUID dagegen wechselt: von 249 Pfaden mit GUID tragen 38 je
nach Archiv verschiedene. Sie muss also vorhanden sein, aber keinen
bestimmten Wert haben.

    py wd_metadaten.py pruefen  <mod.wd> [...]
    py wd_metadaten.py richten  <mod.wd> [...]
"""
import os
import struct
import sys
import zlib

BS = chr(92)
SPIEL = ('F:' + BS + 'SteamLibrary' + BS + 'steamapps' + BS + 'common' + BS
         + 'Two Worlds - Epic Edition')
WDFILES = os.path.join(SPIEL, 'WDFiles')

# Ladereihenfolge des Spiels: spaetere Archive gewinnen. Fuer die Metadaten
# ist das fast egal (siehe Modulkopf), fuer die GUID nehmen wir damit die,
# die das Spiel auch benutzt.
REIHENFOLGE = ('Scripts.wd', 'Levels.wd', 'Parameters.wd', 'Graphics.wd',
               'Update11-15.wd', 'Update16.wd')


def _dir_lesen(pfad):
    """Verzeichnis eines WD 0x200 entpacken. Liefert (bytes, datenteil_laenge)."""
    with open(pfad, 'rb') as f:
        f.seek(-4, 2)
        dir_off = struct.unpack('<I', f.read(4))[0]
        f.seek(0, 2)
        gesamt = f.tell()
        f.seek(-dir_off, 2)
        roh = f.read()
    d = zlib.decompressobj()
    return d.decompress(roh) + d.flush(), gesamt - dir_off


def eintraege(pfad):
    """Alle Verzeichniseintraege als Dicts, in Archivreihenfolge."""
    t, _ = _dir_lesen(pfad)
    off = 8
    anzahl = struct.unpack_from('<H', t, off)[0]
    off += 2
    aus = []
    for _ in range(anzahl):
        nl = t[off]; off += 1
        name = t[off:off + nl].decode('latin-1'); off += nl
        flags, foff, clen, rlen = struct.unpack_from('<BIII', t, off); off += 13
        res, kid, guid = None, None, None
        if flags & 0x08:
            xl = t[off]; off += 1
            res = t[off:off + xl]; off += xl
        if flags & 0x10:
            kid = struct.unpack_from('<I', t, off)[0]; off += 4
        if flags & 0x20:
            guid = t[off:off + 16]; off += 16
        aus.append({'pfad': name, 'flags': flags, 'offset': foff,
                    'clen': clen, 'rlen': rlen, 'res': res, 'id': kid,
                    'guid': guid})
    if off != len(t):
        raise ValueError(f'{pfad}: {len(t) - off} Byte Rest im Verzeichnis')
    return aus


def vorlage(wdfiles=WDFILES):
    """{pfad.lower(): (flags, res, id, guid)} aus den ausgelieferten Archiven."""
    vorhanden = [a for a in os.listdir(wdfiles) if a.lower().endswith('.wd')]
    geordnet = ([a for a in REIHENFOLGE if a in vorhanden]
                + sorted(a for a in vorhanden if a not in REIHENFOLGE))
    aus = {}
    for a in geordnet:                       # spaeter gewinnt
        for e in eintraege(os.path.join(wdfiles, a)):
            aus[e['pfad'].lower()] = (e['flags'], e['res'], e['id'], e['guid'])
    return aus


def pruefen(mod, vorl=None):
    """Abweichungen gegen die Vorlage. Liefert Liste von Meldungen."""
    vorl = vorl if vorl is not None else vorlage()
    schief = []
    for e in eintraege(mod):
        soll = vorl.get(e['pfad'].lower())
        if soll is None:
            continue                          # eigene Datei, keine Vorlage
        s_flags, s_res, s_id, _s_guid = soll
        # EditorDef.txt ist die eine bekannte Uneinheitlichkeit (0x01/0x05).
        if e['pfad'].lower().endswith('editordef.txt'):
            continue
        if (e['flags'], e['res'], e['id']) != (s_flags, s_res, s_id):
            schief.append(
                f"{e['pfad']}: flags={e['flags']:#04x} name={e['res']!r} "
                f"id={e['id']}  ->  soll flags={s_flags:#04x} "
                f"name={s_res!r} id={s_id}")
        elif (s_flags & 0x20) and not e['guid']:
            schief.append(f"{e['pfad']}: GUID fehlt")
    return schief


def richten(mod, ziel=None, vorl=None):
    """Verzeichnis neu schreiben, Metadaten aus der Vorlage uebernehmen.

    Der Datenteil bleibt Byte fuer Byte unangetastet - nur das Verzeichnis
    am Dateiende wird ersetzt, die Offsets darin bleiben damit gueltig.
    """
    vorl = vorl if vorl is not None else vorlage()
    ziel = ziel or mod
    alle = eintraege(mod)
    t, datenlaenge = _dir_lesen(mod)
    with open(mod, 'rb') as f:
        daten = f.read(datenlaenge)
    filetime = t[:8]

    geaendert = 0
    tab = bytearray(filetime) + struct.pack('<H', len(alle))
    for e in alle:
        soll = vorl.get(e['pfad'].lower())
        if soll and not e['pfad'].lower().endswith('editordef.txt'):
            s_flags, s_res, s_id, s_guid = soll
            neu_guid = e['guid'] or s_guid
            if (e['flags'], e['res'], e['id'], bool(e['guid'])) != \
               (s_flags, s_res, s_id, bool(s_guid)):
                geaendert += 1
            e = dict(e, flags=s_flags, res=s_res, id=s_id, guid=neu_guid)
        roh = e['pfad'].encode('latin-1')
        tab += bytes([len(roh)]) + roh
        tab += struct.pack('<BIII', e['flags'], e['offset'], e['clen'],
                           e['rlen'])
        if e['flags'] & 0x08:
            r = e['res'] or b''
            tab += bytes([len(r)]) + r
        if e['flags'] & 0x10:
            tab += struct.pack('<I', e['id'] or 0)
        if e['flags'] & 0x20:
            tab += (e['guid'] or b'')[:16].ljust(16, b'\0')

    komp = zlib.compress(bytes(tab))
    with open(ziel, 'wb') as f:
        f.write(daten)
        f.write(komp)
        f.write(struct.pack('<I', len(komp) + 4))
    return geaendert


def main(argv):
    if len(argv) < 3 or argv[1] not in ('pruefen', 'richten'):
        print(__doc__)
        return 1
    vorl = vorlage()
    print(f'Vorlage: {len(vorl)} Pfade aus den ausgelieferten Archiven\n')
    for mod in argv[2:]:
        schief = pruefen(mod, vorl)
        print(f'{os.path.basename(mod)}: {len(schief)} Abweichung(en)')
        for s in schief:
            print('   ', s)
        if argv[1] == 'richten' and schief:
            n = richten(mod, vorl=vorl)
            rest = pruefen(mod, vorl)
            print(f'    -> {n} Eintraege gerichtet, jetzt noch {len(rest)} offen')
        print()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
