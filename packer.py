"""Pack {inner_path: bytes} into a Two Worlds 1 .wd mod archive.

Packing is delegated to buglord's wdio (the reference repacker) on purpose:
hand-rolled archives looked valid to every reader but the game silently
refused to apply them. Directory metadata (name, class id, GUID) lives only
in the archive directory, so after packing the entries are checked against
the game's own archives (wd_metadaten) and corrected where needed.
"""
import os
import shutil
import tempfile

import wd_metadaten
import wdio

SEP = chr(92)


def pack_mod(out_dir, name, files):
    stage = tempfile.mkdtemp(prefix='tw1pack_')
    try:
        for inner, data in files.items():
            dest = os.path.join(stage, *inner.split(SEP))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, 'wb') as f:
                f.write(data)
        out_wd = os.path.join(out_dir, f'{name}.wd')
        if os.path.exists(out_wd):
            os.remove(out_wd)
        wdio.pack_single(stage, out_wd, 1, None)
        if wd_metadaten.pruefen(out_wd):
            wd_metadaten.richten(out_wd)
        return out_wd
    finally:
        shutil.rmtree(stage, ignore_errors=True)
