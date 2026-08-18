#ifndef STOCKREADONLYSTRATEGY_HPP
#define STOCKREADONLYSTRATEGY_HPP

#include "StrategyEngine.hpp"

// 真实柜台接入的默认策略：消费股票行情和账户回报，但不产生自动订单。
class StockReadOnlyStrategy : public StrategyEngine
{
public:
    StockReadOnlyStrategy()
    {
        m_StrategyID = 2;
    }
};

#endif // STOCKREADONLYSTRATEGY_HPP
