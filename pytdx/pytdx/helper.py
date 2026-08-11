# coding=utf-8

import struct
import six


#### XXX: 分析了一下，貌似是类似utf-8的编码方式保存有符号数字
def get_price(data, pos):
    pos_byte = 6
    bdata = indexbytes(data, pos)
    intdata = bdata & 0x3f
    if bdata & 0x40:
        sign = True
    else:
        sign = False

    if bdata & 0x80:
        while True:
            pos += 1
            bdata = indexbytes(data, pos)
            intdata += (bdata & 0x7f) << pos_byte
            pos_byte += 7

            if bdata & 0x80:
                pass
            else:
                break

    pos += 1

    if sign:
        intdata = -intdata

    return intdata, pos


def get_volume(ivol):
    logpoint = ivol >> (8 * 3)
    hheax = ivol >> (8 * 3);  # [3]
    hleax = (ivol >> (8 * 2)) & 0xff;  # [2]
    lheax = (ivol >> 8) & 0xff;  # [1]
    lleax = ivol & 0xff;  # [0]

    dbl_1 = 1.0
    dbl_2 = 2.0
    dbl_128 = 128.0

    dwEcx = logpoint * 2 - 0x7f
    dwEdx = logpoint * 2 - 0x86
    dwEsi = logpoint * 2 - 0x8e
    dwEax = logpoint * 2 - 0x96
    if dwEcx < 0:
        tmpEax = - dwEcx
    else:
        tmpEax = dwEcx

    dbl_xmm6 = 0.0
    dbl_xmm6 = pow(2.0, tmpEax)
    if dwEcx < 0:
        dbl_xmm6 = 1.0 / dbl_xmm6

    dbl_xmm4 = 0
    if hleax > 0x80:
        tmpdbl_xmm3 = 0.0
        tmpdbl_xmm1 = 0.0
        dwtmpeax = dwEdx + 1
        tmpdbl_xmm3 = pow(2.0, dwtmpeax)
        dbl_xmm0 = pow(2.0, dwEdx) * 128.0
        dbl_xmm0 += (hleax & 0x7f) * tmpdbl_xmm3
        dbl_xmm4 = dbl_xmm0

    else:
        dbl_xmm0 = 0.0
        if dwEdx >= 0:
            dbl_xmm0 = pow(2.0, dwEdx) * hleax
        else:
            dbl_xmm0 = (1 / pow(2.0, dwEdx)) * hleax
        dbl_xmm4 = dbl_xmm0

    dbl_xmm3 = pow(2.0, dwEsi) * lheax
    dbl_xmm1 = pow(2.0, dwEax) * lleax
    if hleax & 0x80:
        dbl_xmm3 *= 2.0
        dbl_xmm1 *= 2.0

    dbl_ret = dbl_xmm6 + dbl_xmm4 + dbl_xmm3 + dbl_xmm1
    return dbl_ret

# 4Bytes 4字节日期时间 按固定算法计算
def get_datetime(category, buffer, pos):
    year = 0
    month = 0
    day = 0
    hour = 15
    minute = 0
    if category < 4 or category == 7 or category == 8:
        (zipday, tminutes) = struct.unpack("<HH", buffer[pos: pos + 4])
        year = (zipday >> 11) + 2004
        month = int((zipday % 2048) / 100)
        day = (zipday % 2048) % 100

        hour = int(tminutes / 60)
        minute = tminutes % 60
    else:
        (zipday,) = struct.unpack("<I", buffer[pos: pos + 4])

        year = int(zipday / 10000)
        month = int((zipday % 10000) / 100)
        day = zipday % 100

    pos += 4

    return year, month, day, hour, minute, pos


def get_time(buffer, pos):
    (tminutes, ) = struct.unpack("<H", buffer[pos: pos + 2])
    hour = int(tminutes / 60)
    minute = tminutes % 60
    pos += 2

    return hour, minute, pos

def indexbytes(data, pos):

    if six.PY2:
        if type(data) is bytearray:
            return data[pos]
        else:
            return six.indexbytes(data, pos)
    else:
        return data[pos]


def decode_bytes(byte_data: bytes, encoding:str ='utf-8'):
    """
    尝试用gbk解码字节数据，失败则尝试utf-8，均失败则打印异常
    :param byte_data: 待解码的字节数据(bytes类型)
    :return: 解码后的字符串或None
    """
    try:
        # 尝试utf-8解码
        return byte_data.decode(encoding).rstrip("\x00")
    except UnicodeDecodeError:
        try:
            # 失败则尝试gbk解码
            if encoding == 'utf-8' or encoding == 'utf8':
                return byte_data.decode("gbk").rstrip("\x00")
            else:
                return byte_data.decode("utf-8").rstrip("\x00")
            
        except UnicodeDecodeError as e:
            # 两种编码都失败，打印异常信息
            print(f"解码失败：无法用utf-8或gbk解码。错误信息：{str(e)}")
            raise


def decode_bytes_safely(byte_data: bytes, encoding:str ='utf-8', tail: bool = False)-> str:
    """
    安全解码包含中文的字节流，兼容末尾字节截断的情况
    :param byte_data: 待解码的字节数据（bytes类型）
    :param encoding: 编码格式（如'utf-8'、'gbk'等）
    :param tail = true 保留尾部1-2字节乱码，默认false不保留，只输出前面正常解码部分
    :return: 解码后的字符串（可能包含部分有效内容）
    """

    # if not byte_data or isinstance(byte_data, bytes):
    if not byte_data:
        return ""
    
    # 尝试直接解码
    try:
        return byte_data.decode(encoding)
    except UnicodeDecodeError:
        # 解码失败，说明存在截断，逐步剔除末尾字节重试
        # 根据编码特性设置最大尝试剔除的字节数（UTF-8最多3字节/字符，GBK最多2字节）
        max_trim = 3 if encoding.lower() in ['utf-8', 'utf8'] else 2
        
        for i in range(1, min(max_trim + 1, len(byte_data) + 1)):
            try:
                # 剔除末尾i个字节后重试
                return byte_data[:-i].decode(encoding, 'ignore' if tail else 'replace')
            except UnicodeDecodeError:
                continue
        
        # 所有尝试失败，返回原始字节的repr（或空字符串，根据需求调整）
        return f"[解码失败] 原始字节: {repr(byte_data)}"