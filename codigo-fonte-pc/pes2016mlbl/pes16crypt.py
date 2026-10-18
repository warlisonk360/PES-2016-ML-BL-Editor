"""
PES 2016 (and later) save-file decryption/encryption.

Algorithm re-implemented from the public-domain project
https://github.com/the4chancup/pesXdecrypter
(originally 'pes16decrypter', by an anonymous contributor; released into the
public domain / Unlicense). MT19937 by Nishimura & Matsumoto (BSD).

Ported to Python for the Linux editor.
"""
import struct

MASK = 0xFFFFFFFF
_N, _M, _MATRIX_A = 624, 397, 0x9908B0DF

ENCRYPTION_HEADER_SIZE = 320
FILEHEADER_SIZE = 176          # PES16/17 struct FileHeader
SERIAL_DOUBLE = 2


class MT19937:
    __slots__ = ("mt", "mti")

    def __init__(self):
        self.mt = [0] * _N
        self.mti = _N + 1

    def init_genrand(self, s):
        self.mt[0] = s & MASK
        for i in range(1, _N):
            prev = self.mt[i - 1]
            self.mt[i] = (1812433253 * (prev ^ (prev >> 30)) + i) & MASK
        self.mti = _N

    def init_by_array(self, key):
        self.init_genrand(19650218)
        i, j = 1, 0
        k = _N if _N > len(key) else len(key)
        while k:
            prev = self.mt[i - 1]
            self.mt[i] = ((self.mt[i] ^ ((prev ^ (prev >> 30)) * 1664525)) + key[j] + j) & MASK
            i += 1
            j += 1
            if i >= _N:
                self.mt[0] = self.mt[_N - 1]
                i = 1
            if j >= len(key):
                j = 0
            k -= 1
        k = _N - 1
        while k:
            prev = self.mt[i - 1]
            self.mt[i] = ((self.mt[i] ^ ((prev ^ (prev >> 30)) * 1566083941)) - i) & MASK
            i += 1
            if i >= _N:
                self.mt[0] = self.mt[_N - 1]
                i = 1
            k -= 1
        self.mt[0] = 0x80000000

    def genrand_int32(self):
        if self.mti >= _N:
            if self.mti == _N + 1:
                self.init_genrand(5489)
            for kk in range(_N - _M):
                y = (self.mt[kk] & 0x80000000) | (self.mt[kk + 1] & 0x7FFFFFFF)
                self.mt[kk] = self.mt[kk + _M] ^ (y >> 1) ^ (_MATRIX_A if (y & 1) else 0)
            for kk in range(_N - _M, _N - 1):
                y = (self.mt[kk] & 0x80000000) | (self.mt[kk + 1] & 0x7FFFFFFF)
                self.mt[kk] = self.mt[kk + (_M - _N)] ^ (y >> 1) ^ (_MATRIX_A if (y & 1) else 0)
            y = (self.mt[_N - 1] & 0x80000000) | (self.mt[0] & 0x7FFFFFFF)
            self.mt[_N - 1] = self.mt[_M - 1] ^ (y >> 1) ^ (_MATRIX_A if (y & 1) else 0)
            self.mti = 0
        y = self.mt[self.mti]
        self.mti += 1
        y ^= (y >> 11)
        y ^= (y << 7) & 0x9D2C5680
        y ^= (y << 15) & 0xEFC60000
        y ^= (y >> 18)
        return y & MASK


def _rol(a, s):
    return ((a << s) | (a >> (32 - s))) & MASK


def _ror(a, s):
    return ((a >> s) | (a << (32 - s))) & MASK


def crypt_stream(key: bytes, data: bytes) -> bytes:
    """Symmetric stream transform. key = 64 bytes."""
    mt = MT19937()
    mt.init_by_array(list(struct.unpack("<16I", key)))
    c0 = mt.genrand_int32()
    c1 = mt.genrand_int32()
    c2 = mt.genrand_int32()
    c3 = mt.genrand_int32()
    n = len(data)
    words = n // 4
    out = bytearray(n)
    if words:
        inp = struct.unpack("<%dI" % words, data[: words * 4])
        res = []
        ap = res.append
        for i in range(words):
            c4 = mt.genrand_int32()
            ap((c4 ^ c3 ^ c2 ^ c1 ^ c0 ^ inp[i]) & MASK)
            c0 = _ror(c1, 15)
            c1 = _rol(c2, 11)
            c2 = _rol(c3, 7)
            c3 = _ror(c4, 13)
        out[: words * 4] = struct.pack("<%dI" % words, *res)
    if n & 3:
        rem = n & 3
        rest = int.from_bytes(data[words * 4:n], "little")
        rest ^= mt.genrand_int32() ^ c3 ^ c2 ^ c1 ^ c0
        out[words * 4:n] = (rest & ((1 << (8 * rem)) - 1)).to_bytes(rem, "little")
    return bytes(out)


def reverse_longs(key: bytes) -> bytes:
    out = bytearray(64)
    for i in range(8):
        for j in range(8):
            out[i * 8 + j] = key[i * 8 + 7 - j]
    return bytes(out)


def _xor_long_param(rolling: bytes, param: int) -> bytes:
    out = bytearray(64)
    for i in range(8):
        q = struct.unpack_from("<Q", rolling, i * 8)[0]
        struct.pack_into("<Q", out, i * 8, q ^ param)
    return bytes(out)


def crypt_header(data: bytes, master_key: bytes) -> bytes:
    header_key = bytearray(data[256:320])
    shuffled = reverse_longs(master_key)
    for i in range(64):
        header_key[i] ^= shuffled[i]
    out = bytearray(crypt_stream(bytes(header_key), data[:320]))
    out[256:320] = data[256:320]
    return bytes(out)


class FileHeader:
    def __init__(self, raw: bytes):
        self.raw = raw
        self.mystery = raw[:64]
        self.data_size, self.logo_size, self.desc_size, self.serial_length = \
            struct.unpack_from("<4I", raw, 64)
        self.hash = raw[80:144]
        self.file_type = raw[144:176].split(b"\x00", 1)[0]

    def pack(self) -> bytes:
        raw = bytearray(self.raw)
        struct.pack_into("<4I", raw, 64, self.data_size, self.logo_size,
                         self.desc_size, self.serial_length)
        return bytes(raw)


class SaveFile:
    """Decrypted representation of a PES save: the six blocks, kept separately."""

    def __init__(self, enc_header, file_header, description, logo, data, serial):
        self.enc_header = enc_header
        self.file_header = file_header
        self.description = description
        self.logo = logo
        self.data = data
        self.serial = serial


def decrypt(blob: bytes, master_key: bytes) -> SaveFile:
    enc_header = crypt_header(blob[:ENCRYPTION_HEADER_SIZE], master_key)
    pos = ENCRYPTION_HEADER_SIZE
    rolling = bytearray(enc_header[:64])
    for i in range(256):
        rolling[i & 63] ^= enc_header[64 + i]
    rolling = bytes(rolling)

    fh_raw = crypt_stream(_xor_long_param(rolling, FILEHEADER_SIZE),
                          blob[pos:pos + FILEHEADER_SIZE])
    pos += FILEHEADER_SIZE
    fh = FileHeader(fh_raw)

    def block(param, size):
        nonlocal pos
        chunk = blob[pos:pos + size]
        pos += size
        return crypt_stream(_xor_long_param(rolling, param), chunk)

    desc = block(0, fh.desc_size)
    logo = block(1, fh.logo_size)
    dat = block(2, fh.data_size)
    serial = block(3, fh.serial_length * SERIAL_DOUBLE)
    return SaveFile(enc_header, fh, desc, logo, dat, serial)


def encrypt(sf: SaveFile, master_key: bytes) -> bytes:
    out = bytearray()
    out += crypt_header(sf.enc_header, master_key)

    rolling = bytearray(sf.enc_header[:64])
    for i in range(256):
        rolling[i & 63] ^= sf.enc_header[64 + i]
    rolling = bytes(rolling)

    fh = sf.file_header
    out += crypt_stream(_xor_long_param(rolling, FILEHEADER_SIZE), fh.pack())

    def emit(param, payload):
        out.extend(crypt_stream(_xor_long_param(rolling, param), payload))

    emit(0, sf.description)
    emit(1, sf.logo)
    emit(2, sf.data)
    emit(3, sf.serial)
    return bytes(out)


# Master keys (public domain data from pesXdecrypter)
MASTER_KEYS = {
    "pes16": bytes([
        0x4D, 0x55, 0x94, 0x66, 0xD9, 0x62, 0x5C, 0xEC,
        0xC1, 0x7C, 0x48, 0x36, 0x77, 0x31, 0x50, 0xE1,
        0x87, 0x1C, 0xB5, 0x6B, 0x41, 0xD4, 0x92, 0x4F,
        0x4A, 0x8C, 0x71, 0x27, 0x0A, 0x0D, 0x50, 0x63,
        0x94, 0x2B, 0x58, 0x5E, 0x99, 0x0B, 0x8B, 0x97,
        0x96, 0x66, 0xC0, 0x00, 0xB7, 0x1D, 0x72, 0x75,
        0xD6, 0xE8, 0x5B, 0x0E, 0xAF, 0xF1, 0x72, 0xD1,
        0xB1, 0xE3, 0x3C, 0x75, 0xDE, 0x9C, 0x13, 0x09,
    ]),
    "pes17": bytes([
        0x9B, 0xC7, 0x13, 0x28, 0x2D, 0xE8, 0x47, 0x75,
        0x4D, 0x52, 0x9E, 0x35, 0x90, 0xAA, 0x6A, 0x7A,
        0x5C, 0xFA, 0x60, 0x9F, 0x6A, 0x32, 0x04, 0x57,
        0xB8, 0x9F, 0x59, 0xA5, 0x5F, 0xAC, 0x7D, 0x62,
        0xFE, 0x10, 0x2A, 0xD6, 0x95, 0xFA, 0xDF, 0xA0,
        0x68, 0xBD, 0x40, 0x95, 0x47, 0x9C, 0xBB, 0x40,
        0xF2, 0x94, 0x49, 0x3C, 0xC8, 0xE0, 0x94, 0x9D,
        0x7B, 0x01, 0x6F, 0xF2, 0xC5, 0x3A, 0x2C, 0xE5,
    ]),
}
