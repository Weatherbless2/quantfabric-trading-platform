#ifndef UITEXT_HPP
#define UITEXT_HPP

#include <QMap>
#include <QString>
#include <QStringList>

namespace UiText
{

inline const QMap<QString, QString>& Translations()
{
    static const QMap<QString, QString> translations = {
        {"Permission", "权限管理"},
        {"Market", "行情"},
        {"EventLog", "事件日志"},
        {"RiskJudge", "风控管理"},
        {"Monitor", "系统监控"},
        {"FutureAnalysis", "期货分析"},
        {"StockAnalysis", "股票分析"},
        {"OrderManager", "委托管理"},
        {"FutureMarket", "期货行情"},
        {"StockMarket", "股票行情"},
        {"SpotMarket", "现货行情"},
        {"OrderStatus", "委托状态"},
        {"AccountFund", "账户资金"},
        {"AccountPosition", "账户持仓"},
        {"ColoStatus", "机房状态"},
        {"AppStatus", "应用状态"},
        {"RiskReport", "风控报告"},
        {"Admin", "管理员"},
        {"Trader", "交易员"},
        {"Risk", "风控员"},
        {"Add", "新增"},
        {"Update", "修改"},
        {"Delete", "删除"},
        {"Buy", "买入"},
        {"Sell", "卖出"},
        {"ReverseRepo", "国债逆回购"},
        {"Subscription", "新股新债申购"},
        {"Allotment", "配股配债"},
        {"CollateralTransferIn", "担保品转入"},
        {"CollateralTransferOut", "担保品转出"},
        {"MarginBuy", "融资买入"},
        {"RepayMarginBySell", "卖券还款"},
        {"ShortSell", "融券卖出"},
        {"RepayStockByBuy", "买券还券"},
        {"RepayStockDirect", "直接还券"},
        {"None", "无"},
        {"Open", "开仓"},
        {"Close", "平仓"},
        {"CloseToday", "平今"},
        {"CloseYestoday", "平昨"},
        {"Check", "检查风控"},
        {"NoCheck", "跳过风控"},
        {"TraderOrder", "交易员委托"},
        {"ForceEndOrder", "强制结束委托"},
        {"In", "转入"},
        {"Out", "转出"}
    };
    return translations;
}

inline QString Display(const QString& value)
{
    return Translations().value(value, value);
}

inline QString Protocol(const QString& value)
{
    const QMap<QString, QString>& translations = Translations();
    for(auto it = translations.cbegin(); it != translations.cend(); ++it)
    {
        if(it.value() == value)
        {
            return it.key();
        }
    }
    return value;
}

inline QString DisplayList(const QString& value)
{
    QStringList items = value.split("|", Qt::SkipEmptyParts);
    for(QString& item : items)
    {
        item = Display(item);
    }
    return items.join("|");
}

inline QString ProtocolList(const QString& value)
{
    QStringList items = value.split("|", Qt::SkipEmptyParts);
    for(QString& item : items)
    {
        item = Protocol(item);
    }
    return items.join("|");
}

}

#endif // UITEXT_HPP
