import argparse
import textwrap
import struct
import zlib
import os
import random
from datetime import datetime, UTC

# TODO PEP

# commands:
# - INFO <target>
# - LIST <target>
# - UNPACK <SRC WD> <DEST DIR> -overwrite
# - PACK <VERSION> <SRC DIR> <DEST WD>

# FILETIME SECTION
EPOCH_AS_FILETIME = 116444736000000000  # January 1, 1970 as MS file time
HUNDREDS_OF_NANOSECONDS = 10000000
def filetime_to_datetime(ft):
    (s, ns100) = divmod(ft - EPOCH_AS_FILETIME, HUNDREDS_OF_NANOSECONDS)
    dt = datetime.utcfromtimestamp(s)
    dt = dt.replace(microsecond=(ns100 // 10))
    return dt
def datetime_to_filetime(dt=datetime.now()):
    ft = dt.timestamp()*HUNDREDS_OF_NANOSECONDS + EPOCH_AS_FILETIME
    return int(ft)

def decompress_stream(strm):#yield when has data?
    dobj = zlib.decompressobj()
    while not dobj.eof:
        yield dobj.decompress(strm.read(1024))
    strm.seek(-len(dobj.unused_data), 1)

def rand_128bit():
    return random.randbytes(16)

class BinRead:
    def __init__(self, data, offset=0):
        self.data = data
        self.offset = offset
    def next(self, form):
        size = struct.calcsize(form)
        self.offset += size
        return struct.unpack(form, self.data[self.offset-size: self.offset])
    def pStr(self):
        [size] = self.next('<B')
        [st] = self.next(f'<{size}s')
        return st.decode('ascii')
    def dStr(self):
        [size] = self.next('<I')
        [st] = self.next(f'<{size}s')
        return st.decode('ascii')
    def pStr2(self):
        [size] = self.next('<B')
        [st] = self.next(f'<{size*2}s')
        return st.decode('utf_16_le')
    def dStr2(self):
        [size] = self.next('<I')
        [st] = self.next(f'<{size*2}s')
        return st.decode('utf_16_le')
    def filetime(self):
        [t] = self.next('<Q')
        return filetime_to_datetime(t)
    def decompress(self, limit=False):
        if limit is False:
            dobj = zlib.decompressobj()
            decomp = b''
            while not dobj.eof:
                decomp+= dobj.decompress(self.data[self.offset])
                self.offset+= 1
        else:
            decomp = zlib.decompress(self.data[self.offset:self.offset+limit])
            self.offset+= limit
        return decomp

def uid_pretty(uid):
    hf = ['{:02X}'.format(a) for a in uid]
    hf = [
        ''.join(hf[0:4]),
        ''.join(hf[4:6]),
        ''.join(hf[6:8]),
        ''.join(hf[8:10]),
        ''.join(hf[10:16])]
    #4–2–2–2-6
    return '-'.join(hf)
def handle_wd1(filestream, header):#version 0x200
    #(0xffa1d031, 'WD', 0x200, 128bit UID)
    #(prehead, header, version, UID)
    filestream.seek(-4,2)
    [dl] = struct.unpack('<I', filestream.read(4))
    filestream.seek(-dl,2)
    d = BinRead(b''.join(decompress_stream(filestream)))
    [FT] = d.next('<Q')#d.filetime()
    [filecount] = d.next('<H')
    filelist = []
    refList = {}
    for _ in range(filecount):
        path = d.pStr()
        [flags, offset, clen, rlen] = d.next('<BIII')
        entry = {
            'FilePath':path,
            'Flags':flags,
            'Offset':offset,
            'Compressed Length':clen,
            'Uncompressed Length':rlen
        }
        if flags & (1<<3):
            entry['Extra String'] = d.pStr()
        if flags & (1<<4):
            entry['Extra Int'] = d.next('<I')[0]
        if flags & (1<<5):
            entry['GUID'] = d.next('<16s')[0]
        refList[path]=len(filelist)
        filelist.append(entry)
    GUID = header[3]
    header = {
        'Version':hex(header[2]),
        'TimeStamp':filetime_to_datetime(FT).strftime('%Y/%m/%d %H:%M'),
        'File Count':filecount,
        'UID':uid_pretty(GUID)
    }
    return {
        'GUID':GUID,
        'FILETIME':FT,
        'FileMap':refList,
        'Version':1,
        'Header':header,
        'Files':filelist
    }

def handle_filelist2(d, filecount):
    filelist = []
    refList = {}
    for _ in range(filecount):
        path = d.pStr()
        [flags, offset, clen, rlen, key] = d.next('<BQIII')
        refList[path]=len(filelist)
        filelist.append({
            'FilePath':path,
            'Flags':flags,
            'Offset':offset,
            'Compressed Length':clen,
            'Uncompressed Length':rlen,
            'Key':key
        })
    return (filelist,refList)

def handle_wd2(filestream, header):#version 0x301
    #('WD', 0x301, 128bit UID, FILETIME, unk,unk,unk,unk, dirLen)
    #(header, version, UID, timestamp, unknown x4, dirLength)
    d = BinRead(b''.join(decompress_stream(filestream)))
    [filecount] = d.next('<I')
    (filelist,refList) = handle_filelist2(d, filecount)
    GUID = header[2]
    FT = header[3]
    header = {
        'Version':hex(header[1]),
        'TimeStamp':filetime_to_datetime(FT).strftime('%Y/%m/%d %H:%M'),
        'File Count':filecount,
        'UID':uid_pretty(GUID)
    }
    return {
        'GUID':GUID,
        'FILETIME':FT,
        'FileMap':refList,
        'Version':2,
        'Header':header,
        'Files':filelist
    }
def handle_wd3(filestream, header):#version 0x401?
    #('WD', 0x401, 128bit UID, FILETIME, unk,unk, name, unk, dirLen)
    #(header, version, UID, timestamp, unk x2, name, unknown, dirLen)
    d = BinRead(b''.join(decompress_stream(filestream)))
    [filecount] = d.next('<I')
    (filelist,refList) = handle_filelist2(d, filecount)
    GUID = header[2]
    FT = header[3]
    header = {
        'Name':header[6].decode(),
        'Version':hex(header[1]),
        'TimeStamp':filetime_to_datetime(FT).strftime('%Y/%m/%d %H:%M'),
        'File Count':filecount,
        'UID':uid_pretty(GUID)
    }
    return {
        'GUID':GUID,
        'FILETIME':FT,
        'FileMap':refList,
        'Version':3,
        'Header':header,
        'Files':filelist
    }

# compressed header 0xffa1d031 starts all files
def init_wd(filestream):
    head = filestream.read(0x24)
    compressed_head = (head[0]==0x78 and head[1]==0x9c)
    valid_head = (head[0]==0x57 and head[1]==0x44)#'WD'
    if compressed_head:#compressed header
        filestream.seek(0,0)#similar to other compress headers
        head = b''.join(decompress_stream(filestream))
        valid_head = (head[4]==0x57 and head[5]==0x44)#'WD'
        head = struct.unpack('<I2sH16s', head)
        version = head[2]
    else:
        head = struct.unpack('<2sH16sQii', head)
        version = head[1]
        if version == 0x301:
            head+= struct.unpack('<iiI',filestream.read(12))
        if version == 0x401:
            [l] = struct.unpack('<I', filestream.read(4))
            head+= struct.unpack(f'<{l}siI', filestream.read(l+8))
    if valid_head:#TODO additional invalidation?
        if version == 0x200:
            return handle_wd1(filestream, head)
        if version == 0x301:
            return handle_wd2(filestream, head)
        if version == 0x401:
            return handle_wd3(filestream, head)
    else:
        raise Exception('Unable to validate header')#TODO better exception?

def com_info(ns):
    with open(ns.file,'rb') as f:
        wdfile = init_wd(f)
    for x in wdfile['Header']:
        print(x.ljust(12)+':', wdfile['Header'][x])
def com_list(ns):
    with open(ns.file,'rb') as f:
        wdfile = init_wd(f)
    for y in wdfile['Files']:
        for x in y:
            if x == 'FilePath':
                print(y[x])
            elif ns.detailed:
                print('-',x.ljust(12)+':', y[x])
def com_overlap(ns):
    with open(ns.fileA, 'rb') as fa:
        wdA = init_wd(fa)
    with open(ns.fileB, 'rb') as fb:
        wdB = init_wd(fb)
    dupecount = 0
    for file in wdA['FileMap']:
        if file in wdB['FileMap']:
            print('found:', file)
            dupecount+=1
    print(dupecount, 'overlapping files')

def make_open(file):
    dp = os.path.dirname(file)
    if not os.path.exists(dp):
        os.makedirs(dp)
    return open(file, 'wb')

MAX_BUFFER = 1000000 # max 1mb per read?
def write_plain(f, fp, offset, clen, flags):
    with make_open(fp) as fo:
        f.seek(offset)
        if flags & 1:
            for bs in decompress_stream(f):
                fo.write(bs)
        else:
            while clen > 0:
                toR = min(clen, MAX_BUFFER)
                fo.write(f.read(toR))
                clen-=toR
#TODO read complex for packing
#-chk uncompressed length when packing
def write_complex_v1(f, fp, offset, clen, flags, file):
    #map file for example <compressed heade><compressed file>
    header = bytes([0xFF, 0xA1, 0xD0, flags])#[3] =0x31 <=> flags? TODO
    if flags & (1<<3):
        header+=struct.pack('<B',len(file['Extra String']))
        header+=bytes(file['Extra String'],'ascii')
    if flags & (1<<4):#TODO test?
        header+=struct.pack('<I', file['Extra Int'])
    if flags & (1<<5):
        header+=struct.pack('<16s', file['GUID'])
    with make_open(fp) as fo:
        fo.write(zlib.compress(header))
        f.seek(offset)
        while clen > 0:#uncompressed if source is
            toR = min(clen, MAX_BUFFER)
            fo.write(f.read(toR))
            clen-=toR
def unpack_v1(f, dest, files):
    filecounter = 0
    for file in files:
        print(file['FilePath'])
        fp = os.path.join(dest, file['FilePath'])
        flags = file['Flags']
        offset = file['Offset']
        clen = file['Compressed Length']
        rlen = file['Uncompressed Length']
        if flags|0b111 == 0b111:#
            write_plain(f, fp, offset, clen, flags)
        else:
            write_complex_v1(f, fp, offset, clen, flags, file)
        filecounter+=1
    print('Files Unpacked', filecounter)

#extracted from "TW2WDTool.exe" by "HeliX666"
_DECKEY = [#195 bytes
    0x36, 0xEF, 0x64, 0xBA, 0x43, 0x39, 0x09, 0xD4, 0x5D, 0xE3, 0xEA, 0x6F,
    0x43, 0x8D, 0xFF, 0x40, 0x03, 0x75, 0x94, 0x1C, 0x4B, 0xA2, 0xF9, 0x43,
    0x10, 0xDF, 0x66, 0x9C, 0x0C, 0x95, 0xED, 0xFE, 0x07, 0x07, 0xA5, 0x77,
    0x3E, 0xEC, 0xD0, 0x98, 0x2D, 0xD1, 0x61, 0xBF, 0x47, 0xE0, 0x2C, 0x77,
    0x16, 0xAE, 0x1F, 0x9B, 0x74, 0x7E, 0x3F, 0xF8, 0x6C, 0xB3, 0x85, 0x24,
    0x02, 0x0C, 0x5F, 0xD5, 0xC0, 0xE8, 0xC1, 0x01, 0x90, 0xE9, 0x29, 0x2F,
    0xEF, 0x25, 0xE5, 0x23, 0x77, 0xF8, 0x38, 0xEA, 0x06, 0x2E, 0x07, 0xC7,
    0x39, 0x02, 0x2A, 0xB6, 0xC2, 0x26, 0x92, 0x2C, 0x3A, 0xB2, 0x3B, 0xFB,
    0x0C, 0x24, 0x0D, 0xCD, 0xEB, 0xC4, 0xEC, 0x70, 0x04, 0xE0, 0x54, 0xFC,
    0x74, 0xFD, 0x3D, 0xBB, 0xCA, 0xE2, 0xCB, 0x0B, 0x2D, 0xCE, 0xE6, 0x52,
    0x0E, 0x62, 0x5E, 0x34, 0xBC, 0x80, 0xF4, 0xB0, 0x18, 0x60, 0x19, 0xD9,
    0x27, 0x08, 0x20, 0x94, 0xC8, 0xA4, 0x98, 0x3E, 0xF6, 0x7E, 0xF7, 0x37,
    0xDE, 0xA6, 0xDF, 0x1F, 0xE1, 0xDA, 0xA2, 0x9E, 0x1A, 0xAE, 0x4A, 0xFE,
    0x69, 0xF2, 0x7A, 0x46, 0xD4, 0xAC, 0xD5, 0x15, 0x63, 0x1C, 0x64, 0x58,
    0xDC, 0x68, 0x8C, 0x32, 0x76, 0x7D, 0x40, 0x7C, 0x12, 0x6A, 0x13, 0xD3,
    0xA5, 0x16, 0x6E, 0x8A, 0xD6, 0xBA, 0x86, 0x30, 0xB8, 0x31, 0xF1, 0xAF,
    0xD0, 0xA8, 0x4C]
#SEARCHING FOR DECRYPTION METHOD
#0x78, 0x9C # TO FIND (key)5425937 -> (index)168
# A = clen
# T1 = not_key_but_related ^ 0x19730811
# T2 = abs(T1)
# T3 = (0x55555556*A)>>32
# T4 = T3+(T3>>31)
# T5 = T4+T2+0x0D
# T6 = T5 % 195 #len(_DECKEY)
# print(T6)
# f.seek(offset)
# (bA,bB) = f.read(2)
# print(hex(bA^_DECKEY[T6]),hex(bB^_DECKEY[T6+1]))
#SAMPLE:
#A = 0xA1C  (is clen?)
#KEY = 0xC55D2B60 (I think) 0x410381fc
#T1 = 0xDC2E2371 (fits condition)
#T2 = 0x23D1DC8F (negates)
#T3 = (0x55555556 * A)>>32?
#T4 = T3+(T3>>31)
#T5 = T4+T2+0x0D
#T6 = T5 % 195 (length of deckey)

def write_decrypt(f, fp, offset, clen, flags, key):
    if flags&1 != 1:
        #can only brute force compressed files
        raise NotImplementedError
    #Find Start Offset
    off=0
    f.seek(offset)
    (tA,tB) = f.read(2)
    while off<195:
        if (tA^_DECKEY[(off)%195])==0x78:
            if (tB^_DECKEY[(off+1)%195])==0x9C:
                break
        off+=1
    if off==195:
        raise KeyError
    with make_open(fp) as fo:
        f.seek(offset)
        dobj = zlib.decompressobj()
        for i in range(clen):
            rB = f.read(1)[0]^_DECKEY[(off+i)%195] #len(_DECKEY)=195
            fo.write(dobj.decompress(bytes([rB])))
def unpack_v2(f, dest, files):
    filecounter=0
    for file in files:
        print(file['FilePath'])
        fp = os.path.join(dest, file['FilePath'])
        flags = file['Flags']
        offset = file['Offset']
        clen = file['Compressed Length']
        rlen = file['Uncompressed Length']
        key = file['Key']
        #brute force decrypt, all compressed
        if flags|0b111 == 0b111:#
            write_plain(f, fp, offset, clen, flags)
        else:
            write_decrypt(f, fp, offset, clen, flags, file)
        filecounter+=1
    print('Files Unpacked', filecounter)
def unpack_bulk(i,o,p):
    files = list(filter(lambda x: x.endswith('.wd'), os.listdir(i)))
    print('Unpacking', len(files), 'archives')
    for file in files:
        ni = os.path.join(i,file)
        no = os.path.join(o,file[:-3])+'\\'
        print(ni,' -> ',no)
        unpack_single(ni,no,p)
def unpack_single(i,o,p=False):
    with open(i, 'rb') as fs:
        wdfile = init_wd(fs)
        if p:
            with make_open(os.path.join(o,'GUID')) as fg:
                fg.write(wdfile['GUID'])
            with make_open(os.path.join(o,'FILETIME')) as ft:
                ft.write(struct.pack('<Q',wdfile['FILETIME']))
        if wdfile['Version'] == 1:
            return unpack_v1(fs, o, wdfile['Files'])
        if wdfile['Version'] >= 2:
            return unpack_v2(fs, o, wdfile['Files'])
def com_unpack(ns):
    #print(ns)
    i = ns.source
    o = ns.destination
    if not o:
        o = os.path.abspath(os.path.splitext(i)[0])
    if (not ns.overwrite) and os.path.exists(o) and (len(os.listdir(o)) > 0):
        raise FileExistsError
    print('Unpacking',i,'to',o)
    if ns.bulk:
        return unpack_bulk(i,o,ns.preserve)
    else:
        return unpack_single(i,o,ns.preserve)
def get_filelist(i):
    files = []
    for (dirpath, dirnames, filenames) in os.walk(i):
        for file in filenames:
            fpath = os.path.join(dirpath, file)
            rpath = os.path.relpath(fpath, start=i)
            files.append([fpath, rpath])
    return files
_TEXT_FILES_ = ['.txt','.con','.tga','.cfg','.def','.qtx']
def v1_chk_file(file):
    with open(file, 'rb') as f:
        head = f.read(2)
        compressed_head = False
        if len(head) >= 2:
            compressed_head = (head[0]==0x78 and head[1]==0x9c)
        if compressed_head:
            f.seek(0)
            head = b''.join(decompress_stream(f))
            return (f.tell(),head[3],head[4:])
        else:
            (_, ext) = os.path.splitext(file)
            if ext in _TEXT_FILES_:#TODO check if right?
                return (False,0b101, b'')
            elif ext == '.phx':#compression not allowed on map Physx file
                return (False,0, b'')
            else:
                return (False,0x1, b'')
def file_to_archive(fs, file, special, flags):
    compress = flags & 0x1
    offset = fs.tell()
    clen = 0
    rlen = 0
    with open(file, 'rb') as f:
        if special:
            f.seek(special)
            dobj = zlib.decompressobj()
            while not dobj.eof:
                buf = f.read(MAX_BUFFER)
                rlen += len(dobj.decompress(buf))
                fs.write(buf)
        else:
            if compress:
                compobj = zlib.compressobj()
                for chunk in iter(lambda: f.read(MAX_BUFFER), b''):
                    fs.write(compobj.compress(chunk))
                fs.write(compobj.flush())
            else:
                for chunk in iter(lambda: f.read(MAX_BUFFER), b''):
                    fs.write(chunk)
            rlen = f.tell()
    clen = fs.tell()-offset
    return (offset, clen, rlen)

def pack_v1(fs, i):
    header = bytes([0xFF, 0xA1, 0xD0, 0x31])
    header+= bytes([0x57, 0x44, 0x00, 0x02])#'WD',0x200
    pG = os.path.join(i,'GUID')
    if os.path.exists(pG):
        with open(pG, 'rb') as fg:
            header+= fg.read()
    else:
        header+= rand_128bit()
    fs.write(zlib.compress(header))
    timestamp = datetime_to_filetime()
    pT = os.path.join(i,'FILETIME')
    if os.path.exists(pT): #TODO add to command line?
        with open(pT, 'rb') as ft:
            [timestamp] = struct.unpack('<Q',ft.read())
    dirEntries = []
    for (fpath, rpath) in get_filelist(i):
        if rpath in ['GUID','FILETIME']: continue
        print('Packing', rpath)
        (special, flags, extra) = v1_chk_file(fpath)
        (offset, clen, rlen) = file_to_archive(fs, fpath, special, flags)
        dirEntries.append([
            rpath,
            offset, 
            clen, 
            rlen, 
            flags, 
            extra])
    dirB = struct.pack('<QH',timestamp, len(dirEntries))
    for (path, off, cl, rl, flags, extra) in dirEntries:
        pathB = bytes(path, 'ascii')
        pathL = len(pathB)
        dirB+=struct.pack(
            f'<B{pathL}sB3I', 
            pathL, pathB, flags, off, cl, rl)
        dirB+=extra
    cDir = zlib.compress(dirB)
    fs.write(cDir)
    fs.write(struct.pack('<I', len(cDir)+4))
def common_head_v2_v3(i,v):
    GUID = rand_128bit()
    pG = os.path.join(i,'GUID')
    if os.path.exists(pG):
        with open(pG, 'rb') as fg:
            GUID = fg.read()
    timestamp = datetime_to_filetime()
    pT = os.path.join(i,'FILETIME')
    if os.path.exists(pT): #TODO add to command line?
        with open(pT, 'rb') as ft:
            [timestamp] = struct.unpack('<Q',ft.read())
    header = bytes([0x57, 0x44])
    if v==2:
        header+= bytes([0x01, 0x03])#'WD',0x301
    elif v==3:
        header+= bytes([0x01, 0x04])#'WD',0x401
    header+= GUID
    header+= struct.pack('<Q',timestamp)
    header+= struct.pack('<II',0,1)
    return header
def _getNameLenghts(files):
    l = 0
    for (fpath, rpath) in files:
        l+= len(rpath)
    return l
def pack_file_v2(fs, i):
    files = get_filelist(i)
    ftlen = _getNameLenghts(files)
    mdl = len(files)*21+ftlen+0x10 #max dir length?
    prelim_dirL = max(mdl, 0x1000)
    fs.seek(prelim_dirL, os.SEEK_CUR)
    dirEntries = []
    for (fpath, rpath) in files:
        if rpath in ['GUID','FILETIME']: continue
        print('Packing', rpath)
        (offset, clen, rlen) = file_to_archive(fs, fpath, False, 0x1)
        dirEntries.append([
            rpath,
            offset, 
            clen, 
            rlen, 
            0x1, 
            0x0])
    return dirEntries
def makedir_v2(entries):
    dirB = struct.pack('<I',len(entries))
    for (path, off, cl, rl, flags, key) in dirEntries:
        pl = len(path)
        dirB+= struct.pack(
            f'<B{pl}sBQIII',
            pl,
            path,
            flags,
            off,#Q, 64 bit offset
            cl,
            rl,
            key)
    return dirB
def pack_v2_v3_finish(fs, i):
    dirL_ptr = fs.tell()
    directory = pack_file_v2(fs, i)
    dirB = zlib.compress(makedir_v2(directory))
    dirL = len(dirB)
    fs.seek(dirL_ptr)
    fs.write(struct.pack('<I',dirL))
    fs.write(dirB)
def pack_v2(fs, i):
    header = common_head_v2_v3(i,2)
    header+= struct.pack('<II',0,0)
    fs.write(header)
    pack_v2_v3_finish(fs, i)
def pack_v3(fs, i, fName):
    header = common_head_v2_v3(i,3)
    fNameL = len(fName)
    header+= struct.pack(f'<I{fNameL}sI',fNameL,fName,0)
    fs.write(header)
    pack_v2_v3_finish(fs, i)
def pack_bulk(i,o,v,n):
    folders = list(filter(
        lambda x: os.path.isdir(os.path.join(i,x)),
        os.listdir(i)))
    print('Packing', len(folders), 'archives')
    for folder in folders:
        ni = os.path.join(i,folder)
        no = os.path.join(o,folder+'.wd')
        print(ni,' -> ',no)
        pack_single(ni,no,v,n)
def pack_single(i,o,v,n):
    with make_open(o) as fs:
        if v == 1:
            return pack_v1(fs, i)
        elif v == 2:
            return pack_v2(fs, i)
        elif v == 3:
            if not n:
                n = os.path.basename(o)
            return pack_v3(fs, i, n)
def com_pack(ns):
    i = ns.source
    o = ns.destination
    if not o:
        o = os.path.abspath(i)
        if not ns.bulk:
            o+='.wd'
    if (not ns.overwrite) and os.path.exists(o):
        raise FileExistsError
    print('Packing',i,'to',o)
    if ns.bulk:
        return pack_bulk(i,o,ns.version, ns.name)
    else:
        return pack_single(i,o,ns.version, ns.name)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='packer & unpacker for WD archive')
    commands = parser.add_subparsers(title='commands')
    c_info = commands.add_parser('info', help='outputs header information')
    c_info.add_argument(
        'file',
        #type=argparse.FileType('rb'),
        help='file to inspect')
    c_info.set_defaults(func=com_info)

    c_list = commands.add_parser('list', help='lists files in archive')
    c_list.add_argument(
        'file',
        help='file to inspect')
    c_list.add_argument(
        '-d', '--detailed',
        action='store_true',
        help='detailed output')
    c_list.set_defaults(func=com_list)
    
    c_overlap = commands.add_parser('overlap', help='checks for file overlap')
    c_overlap.add_argument(
        'fileA',
        help='first file to compare')
    c_overlap.add_argument(
        'fileB',
        help='second file to compare')
    c_overlap.set_defaults(func=com_overlap)

    c_unpack = commands.add_parser('unpack', help='unpacks archive')
    c_unpack.add_argument('-o', '--overwrite',
                          action='store_true',
                          help='overwrite existing')
    c_unpack.add_argument('-p', '--preserve',
                          action='store_true',
                          help='also stores GUID and TIMESTAMP')
    c_unpack.add_argument('-b', '--bulk',#TODO auto detect?
                          action='store_true',
                          help='unpack all archives in source folder')
    c_unpack.add_argument('source', help='source to unpack')
    c_unpack.add_argument('destination',
                          nargs='?',
                          help='destination to unpack to')
    c_unpack.set_defaults(func=com_unpack)
    
    c_pack = commands.add_parser(
        'pack',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent('''\
            packs a WD archive of specified version
            Archive versions:
              1 - 0x200 - Two worlds 1
              2 - 0x301 - Two worlds 2
              3 - 0x401 - Vendetta: Curse of Ravens Cry
            '''),
        help='packs an archive')
    c_pack.add_argument('-o', '--overwrite',
                        action='store_true',
                        help='overwrite existing')
    c_pack.add_argument('-b', '--bulk',#TODO auto detect?
                        action='store_true',
                        help='pack all folders in source folder')
    c_pack.add_argument('-v', '--version',
                        required=True,
                        type=int,
                        choices=(1,2,3),
                        help='archive version')
    c_pack.add_argument('-n', '--name',
                        help='archive name, only used for archive version 3')
    c_pack.add_argument('source', help='source to pack')
    c_pack.add_argument('destination',
                        nargs='?',
                        help='destination to pack to')
    c_pack.set_defaults(func=com_pack)
    args = parser.parse_args()
    if hasattr(args, 'func'):
        args.func(args)
    else:
        parser.print_help()
