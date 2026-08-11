# coding=utf-8

from OxQuant.pytdx.parser.base import BaseParser
from OxQuant.pytdx.helper import get_datetime, get_volume, get_price
from collections import OrderedDict
import struct
"""
这个是获取大连商品的数据

OrderedDict([('market', 29),
              ('category', 3),
              ('name', '大连商品'),
              ('short_name', 'QD')]),


1d 是请求的数据数量，

01 c1 06 0b 00 02 0b 00  0b 00 00 24 1d 00 00 00 00 1d 00 01 00
"""

class GetInstrumentQuoteList(BaseParser):

    def setParams(self, market, category, start, count):
        pkg = bytearray.fromhex("01 c1 06 0b 00 02 0b 00 0b 00 00 24")
        pkg.extend(
            struct.pack("<BHHHH", market, 0, start, count, 1)
        )
        self.category = category
        self.send_pkg = pkg

    def parseResponse(self, body_buf):

        pos = 0
        (num,) = struct.unpack('<H', body_buf[pos: pos+2])
        pos += 2

        if num == 0:
            return []

        datalist = []
        if self.category not in [2,3] :
            return NotImplementedError("暂时不支持期货,港股之外的品类")

        for i in range(num):
            """
            每个块一共300bytes
            """
            market, code = struct.unpack("<B9s", body_buf[pos: pos + 10])
            code = code.strip(b"\0").decode("gbk") # to unicode
            pos += 10
            if self.category == 3:
                try:
                    pos = self.extract_futures(market, code, body_buf, datalist, pos)
                except Exception as e:
                    print(e)
                # print(pos)
            elif self.category == 2:
                """
                   market  category   name short_name
                0      31         2   香港主板         KH
                1      48         2  香港创业板         KG
                2      49         2   香港基金         KT
                3      71         2    沪港通         GH
                """
                pos = self.extract_hongkong_stocks(market, code, body_buf, datalist, pos)

        return datalist

    def extract_hongkong_stocks(self, market, code, body_buf, datalist, pos):
        """
        :param body_buf[out]:
        :param datalist[out]:
        :param pos[out]:
        :return:
        """
        data_pack_format = "<IfffffIfIIfIIIIfffffIIIIIfffffIIIII"
        (HuoYueDu,
         ZuoShou,
         JinKai,
         ZuiGao,
         ZuiDi,
         XianJia,
         _,  # 0
         MaiRuJia,  # ?
         ZongLiang,
         XianLiang,  # ?
         ZongJinE,
         _,  # ?
         _,  # ?
         Nei,  # 0
         Wai,  # 0 Nei/Wai = 内外比？
         MaiRuJia1,
         MaiRuJia2,
         MaiRuJia3,
         MaiRuJia4,
         MaiRuJia5,
         MaiRuLiang1,
         MaiRuLiang2,
         MaiRuLiang3,
         MaiRuLiang4,
         MaiRuLiang5,
         MaiChuJia1,
         MaiChuJia2,
         MaiChuJia3,
         MaiChuJia4,
         MaiChuJia5,
         MaiChuLiang1,
         MaiChuLiang2,
         MaiChuLiang3,
         MaiChuLiang4,
         MaiChuLiang5) = struct.unpack(data_pack_format, body_buf[pos: pos + 140])
        pos += 290
        one = OrderedDict([
            ("market", market),
            ("code", code),
            ("HuoYueDu", HuoYueDu),
            ("ZuoShou", ZuoShou),
            ("JinKai", JinKai),
            ("ZuiGao", ZuiGao),
            ("ZuiDi", ZuiDi),
            ("XianJia", XianJia),
            ("MaiRuJia", MaiRuJia),
            ("ZongLiang", ZongLiang),
            ("XianLiang", XianLiang),
            ("ZongJinE", ZongJinE),
            ("Nei", Nei),
            ("Wai", Wai),  # 0 Nei/Wai = 内外比？
            ("MaiRuJia1", MaiRuJia1),
            ("MaiRuJia2", MaiRuJia2),
            ("MaiRuJia3", MaiRuJia3),
            ("MaiRuJia4", MaiRuJia4),
            ("MaiRuJia5", MaiRuJia5),
            ("MaiRuLiang1", MaiRuLiang1),
            ("MaiRuLiang2", MaiRuLiang2),
            ("MaiRuLiang3", MaiRuLiang3),
            ("MaiRuLiang4", MaiRuLiang4),
            ("MaiRuLiang5", MaiRuLiang5),
            ("MaiChuJia1", MaiChuJia1),
            ("MaiChuJia2", MaiChuJia2),
            ("MaiChuJia3", MaiChuJia3),
            ("MaiChuJia4", MaiChuJia4),
            ("MaiChuJia5", MaiChuJia5),
            ("MaiChuLiang1", MaiChuLiang1),
            ("MaiChuLiang2", MaiChuLiang2),
            ("MaiChuLiang3", MaiChuLiang3),
            ("MaiChuLiang4", MaiChuLiang4),
            ("MaiChuLiang5", MaiChuLiang5),
        ])
        datalist.append(one)
        return pos

    def extract_futures(self, market, code, body_buf, datalist, pos):
        data_pack_format = "<IfffffIIIIfIIfIfIIIIIIIIIfIIIIIIIII"

        (BiShu, ZuoJie, JinKai, ZuiGao, ZuiDi, MaiChu, KaiCang, _, ZongLiang,
        XianLiang, ZongJinE, NeiPan, WaiPan, _, ChiCangLiang, MaiRuJia, _, _, _, _, MaiRuLiang,
        _, _, _, _, MaiChuJia, _, _, _, _, MaiChuLiang, _, _, _, _) = struct.unpack(data_pack_format, body_buf[pos: pos + 140])
        pos += 290
        one = OrderedDict([
            ("market", market),
            ("code", code),
            ("BiShu", BiShu),
            ("ZuoJie", ZuoJie),
            ("JinKai", JinKai),
            ("ZuiGao", ZuiGao),
            ("ZuiDi", ZuiDi),
            ("MaiChu", MaiChu),
            ("KaiCang", KaiCang),
            ("ZongLiang", ZongLiang),
            ("XianLiang", XianLiang),
            ("ZongJinE", ZongJinE),
            ("NeiPan", NeiPan),
            ("WaiPan", WaiPan),
            ("ChiCangLiang", ChiCangLiang),
            ("MaiRuJia", MaiRuJia),
            ("MaiRuLiang", MaiRuLiang),
            ("MaiChuJia", MaiChuJia),
            ("MaiChuLiang", MaiChuLiang)
        ])
        datalist.append(one)
        return pos

EXT_MAX_RECORD_COUNT = 80

if __name__ == '__main__':
    # from OxQuant.pytdx.exhq import TdxExHq_API

    # apiX = TdxExHq_API()
    # # with api.connect('119.97.142.130', 7721):
        #print(api.to_df(api.get_instrument_quote_list(71, 2, 0, 10)))
    #     print(apiX.to_df(apiX.get_instrument_quote_list(47, 3, 0, 80)))
    from OxQuant.pytdx.exhq import TdxExHq_API
    import pandas as pd
    from datetime import datetime
    import os
    apiX = TdxExHq_API(raise_exception=True)
    init_time = datetime.now()

    with apiX.connect('116.205.143.214', 7727): # 扩展市场广州双线1
        iCnt = 0
        nTotal = 0
        nCurrRows = 0
        all_data = pd.DataFrame()
        end_time = datetime.now()
        print(f"Start Time: {init_time}, End Time: {end_time}, Elapsed Time(ms): {(end_time - init_time).total_seconds() * 1000}")

        for mkt in [28, 29, 30, 42, 47, 60, 65, 66]: # 国内期货市场
            iCnt = 0
            nCurrRows = 0
            while True:
                start_time = datetime.now()
                df = pd.DataFrame(apiX.get_instrument_quote_list(mkt, 3, iCnt * EXT_MAX_RECORD_COUNT, EXT_MAX_RECORD_COUNT)) # 每次最多返回80条数据
                iCnt += 1
                nCurrRows = len(df)
                print(f"Times: {iCnt}, nCurrRows: {nCurrRows}")
                if nCurrRows > 0:
                    print(df)
                    nTotal += nCurrRows
                    all_data = pd.concat([all_data, df], axis=0)
                
                if nCurrRows < EXT_MAX_RECORD_COUNT:
                    break
                
                end_time = datetime.now()
                print(f"Start Time: {start_time}, End Time: {end_time}, Elapsed Time(ms): {(end_time - start_time).total_seconds() * 1000}")
        
        all_data.set_index(['market', 'code'], inplace=True)
        all_data.sort_index(inplace=True)
        csvFile = os.path.join(os.getcwd(), "data_tdx", "EXT_instrument_quote_list.csv")
        all_data.to_csv(csvFile, index=True, encoding='utf-8-sig')
        print(f'All Data[{nTotal} rows]Save In File[{csvFile}]')
        end_time = datetime.now()
        print(
            f"Start Time: {init_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}, "
            f"End Time: {end_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}, "
            f"Elapsed Time(ms): {(end_time - init_time).total_seconds() * 1000:.3f}"
            )
