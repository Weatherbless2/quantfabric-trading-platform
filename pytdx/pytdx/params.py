# coding=utf-8
import os
# VIPDOC_PATH = os.getenv("TDX_VIPDOC", "")

class TDXParams:

    # 产品类型
    CATEGORY_NONE = 0  # 无
    CATEGORY_FUTURE = 8  # 期货
    CATEGORY_OPTION = 1  # 期权
    CATEGORY_STOCK = 2  # 股票
    CATEGORY_INDEX = 3  # 指数
    CATEGORY_FUND = 4  # 基金
    CATEGORY_BOND = 5  # 债券
    CATEGORY_ETF = 6  # ETF
    CATEGORY_SPOT = 7  # 现货

    # 拓展市场产品类型（EX）
    CATEGORY_EX_STOCK  = 1  # 股票（EXT API）
    CATEGORY_EX_HKSTK  = 2  # 香港主板 KH、香港创业板KG、香港基金KT、港股暗盘AP
    CATEGORY_EX_FUTURE = 3  # 期货
                            # 28 郑州商品
                            # 29 大连商品
                            # 30 上海期货
                            # 42 商品指数
                            # 47 中金所期货
                            # 60 主力期货合约
                            # 65 广州套利期货
                            # 66 广州期货

    CATEGORY_EX_RATE = 4    # 汇率
                            # 10 基本汇率 FE
                            # 11 交叉汇率 FX

    CATEGORY_EX_INDEX = 5   # 指数
                            # 12 国际指数 WI  
                            # 27 香港指数 FH
                            # 62 中证指数 ZZ
                            # 68 风控指数 TZ
                            # 69 华证指数 BZ
                            # 70 扩展板块指数 UZ
                            # 102 国证指数 GZ
    CATEGORY_EX_BOND = 6    # 国债预发行，基金估值
                            # 54 国债预发行	GY
                            # 93 基金估值	JG

    CATEGORY_EX_CASH = 7    # 91 资金市场
    CATEGORY_EX_FUND = 8    # 基金理财
                            # 33 开放式基金	FU
                            # 56 阳光私募基金	TA
                            # 57 券商集合理财	TB

    CATEGORY_EX_CURRENCY = 9 # 货币基金
                            # 34 货币型基金	FB
                            # 58 券商货币理财	TC

    CATEGORY_EX_MACRO   = 10 # 38 宏观指标	HG
    CATEGORY_EX_SH_GOLD = 11 # 46 上海黄金	SG
                             # 100 代码镜像	CM ???

    CATEGORY_EX_OPTION  = 12 # 46 期权
                             # 4 郑州商品期权	OZ
                             # 5 大连商品期权	OD
                             # 6 上海商品期权	OS
                             # 7 中金所期权	    OJ
                             # 8 上海股票期权	QQ
                             # 9 深圳股票期权	SQ
                             # 24 香港金融期权	PJ
                             # 26 香港股票期权	PQ
                             # 67 广州期权	   OG

    CATEGORY_EX_DEU     = 14 # 73 德国股票  DE
    CATEGORY_EX_USA     = 13 # 74 美国股票  US
    CATEGORY_EX_SGP     = 15 # 78 新加坡股票 SE


    #市场
    MARKET_NONE = None  # 深圳
    MARKET_SZ = 0  # 深交所
    MARKET_SH = 1  # 上交所
    MARKET_TEMP = 1  # 临时股（EXT API）
    MARKET_BJ = 44  # 北交所（股转系统）
    MARKET_XSB = 93  # 北京 TDX 代码，非系统内部代码

    #K线种类
    # K 线种类
    # 0 -   5 分钟K 线
    # 1 -   15 分钟K 线
    # 2 -   30 分钟K 线
    # 3 -   1 小时K 线
    # 4 -   日K 线
    # 5 -   周K 线
    # 6 -   月K 线
    # 7 -   1 分钟
    # 8 -   1 分钟K 线
    # 9 -   日K 线
    # 10 -  季K 线
    # 11 -  年K 线

    KLINE_TYPE_5MIN = 0
    KLINE_TYPE_15MIN = 1
    KLINE_TYPE_30MIN = 2
    KLINE_TYPE_1HOUR = 3
    KLINE_TYPE_DAILY = 4
    KLINE_TYPE_WEEKLY = 5
    KLINE_TYPE_MONTHLY = 6
    KLINE_TYPE_EXHQ_1MIN = 7
    KLINE_TYPE_1MIN = 8
    KLINE_TYPE_RI_K = 9
    KLINE_TYPE_3MONTH = 10
    KLINE_TYPE_YEARLY = 11


    # ref : https://github.com/rainx/pytdx/issues/7
    # 分笔行情最多2000条
    MAX_TRANSACTION_COUNT = 2000
    # k先数据最多800条
    MAX_KLINE_COUNT = 800

    # 板块相关参数
    BLOCK_SZ = "block_zs.dat"
    BLOCK_FG = "block_fg.dat"
    BLOCK_GN = "block_gn.dat"
    BLOCK_DEFAULT = "block.dat"

    vipdoc_env = os.getenv("TDX_VIPDOC", "")
    VIPDOC = "C:\\new_tdx\\vipdoc" if vipdoc_env == "" or vipdoc_env is None else vipdoc_env # 默认安装路径-不含专业财务数据
    # VIPDOC = "\\GTJA\\RichEZ\\newVer\\vipdoc" # 券商版本参考路径-可以下载专业财务数据
    # VIPDOC = "D:\\new_tdx\\vipdoc\\hsjday" # 自定义下载文件参考路径

