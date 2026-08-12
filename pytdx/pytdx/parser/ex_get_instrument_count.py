# coding=utf-8

from OxQuant.pytdx.parser.base import BaseParser
from OxQuant.pytdx.helper import get_datetime, get_volume, get_price
from collections import OrderedDict
import struct

# bytearray(b'TDX_DS\x00\x00\x00\x00\x00\x1f\xdc\x00\x00\x01\x00\x00\x00=\x9c\x00\x00t\x00\x00\x00\x00\x00\x00\x00')
# bytearray(      b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00.\xdd\x08\x00\x04\x00\x00\x00x\xe1\x01\x00\xd7\x00\x00\x00\x00\x0em\x01')
class GetInstrumentCount(BaseParser):

    def setup(self):
        self.send_pkg = bytearray.fromhex("01 03 48 66 00 01 02 00 02 00 f0 23")

    def parseResponse(self, body_buf):
        pos = 0
        (num,) = struct.unpack("<I", body_buf[19: 19+4]) # 从第19个字节开始 unpack 4个字节的无符号整数
        print(f"GetInstrumentCount: num = {num} \n")

        return num


if __name__ == '__main__':
    from OxQuant.pytdx.exhq import TdxExHq_API

    apiX = TdxExHq_API()
    # api.connect('120.25.218.6', 7727) # 扩展市场深圳主站
    # with apiX.connect('112.74.214.43', 7727): # 扩展市场深圳双线1
    with apiX.connect('116.205.143.214', 7727): # 扩展市场广州双线1
        rowCnt = apiX.get_instrument_count()
        print(f"rowCnt = {rowCnt} \n")