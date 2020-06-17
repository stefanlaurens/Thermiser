class crc(object):

    ltH = [0x00, 0x10, 0x20, 0x30, 0x40, 0x50, 0x60, 0x70,0x81, 0x91, 0xa1, 0xb1, 0xc1, 0xd1, 0xe1, 0xf1]
    ltL = [0x00, 0x21, 0x42, 0x63, 0x84, 0xa5, 0xc6, 0xe7,0x08, 0x29, 0x4a, 0x6b, 0x8c, 0xad, 0xce, 0xef]

    def __init__(self):
        self.hi = 0XFF
        self.lo = 0XFF

    def _updateNibble(self, byte):
        t = self.hi >> 4
        t = t ^ byte

        self.hi = ((self.hi << 4) | (self.lo >> 4)) & 0xFF
        self.hi = self.hi ^ self.ltH[t]
        self.hi = self.hi & 0xFF

        self.lo = (self.lo << 4) & 0xFF
        self.lo = self.lo ^ self.ltL[t]
        self.lo = self.lo & 0xFF

    def ccitt(self, data):
        """Calculates a CCITT CRC and returns a tuple containing low and high bytes"""
        self.hi = 0XFF
        self.lo = 0XFF
        for byte in data:
            self._updateNibble(byte>>4)
            self._updateNibble(byte & 0x0f)
        return [self.lo, self.hi]

    def addCCITTtoBytearray(self, data):
        """Calculates CCITT CRC over first (n-2) bytes of the buffer and stores result at end of buffer"""
        lo, hi = self.ccitt(data[:(len(data)-2)])
        data[len(data)-2] = lo
        data[len(data)-1] = hi
        return data

    def verifyCCITTfromByteArray(self, data):
        """Calculates CCITT CRC over first (n-2) bytes of data and compares
        with crc stored as last two bytes of data."""
        if data is None:
            return False
        if len(data) < 3:
            return False
        lo, hi = self.ccitt(data[:(len(data)-2)])

        if data[len(data)-2] == lo and data[len(data)-1] == hi:
            return True
        else:
            return False
