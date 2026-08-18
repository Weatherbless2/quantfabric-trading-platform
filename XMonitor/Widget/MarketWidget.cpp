#include "MarketWidget.h"

namespace
{
MarketData::TFutureMarketData ToTableMarketData(const MarketData::TStockMarketData& stock)
{
    MarketData::TFutureMarketData data = {};
    strncpy(data.Colo, stock.Colo, sizeof(data.Colo) - 1);
    strncpy(data.Broker, stock.Broker, sizeof(data.Broker) - 1);
    strncpy(data.Ticker, stock.Ticker, sizeof(data.Ticker) - 1);
    strncpy(data.ExchangeID, stock.ExchangeID, sizeof(data.ExchangeID) - 1);
    strncpy(data.UpdateTime, stock.UpdateTime, sizeof(data.UpdateTime) - 1);
    strncpy(data.RecvLocalTime, stock.RecvLocalTime, sizeof(data.RecvLocalTime) - 1);
    data.LastTick = stock.LastTick;
    data.Tick = stock.Tick;
    data.TotalTick = stock.Tick + 1;
    data.MillSec = stock.MillSec;
    data.LastPrice = stock.LastPrice;
    data.Volume = stock.Volume;
    data.Turnover = stock.Turnover;
    data.PreSettlementPrice = stock.PreClosePrice;
    data.PreClosePrice = stock.PreClosePrice;
    data.OpenInterest = stock.OpenInterest;
    data.OpenPrice = stock.OpenPrice;
    data.HighestPrice = stock.HighestPrice;
    data.LowestPrice = stock.LowestPrice;
    data.UpperLimitPrice = stock.UpperLimitPrice;
    data.LowerLimitPrice = stock.LowerLimitPrice;
    data.BidPrice1 = stock.BidPrice[0];
    data.BidVolume1 = stock.BidVolume[0];
    data.AskPrice1 = stock.AskPrice[0];
    data.AskVolume1 = stock.AskVolume[0];
    data.ErrorID = stock.ErrorID;
    return data;
}
}

MarketWidget::MarketWidget(QWidget *parent) : FinTechUI::TabPageWidget(parent)
{
    InitFilterWidget();
    InitMarketTableView();
    InitKCustomPlot();

    QSplitter* RightSplitter = new QSplitter(Qt::Vertical);
    RightSplitter->addWidget(m_MarketTableView);
    RightSplitter->addWidget(m_KCustomPlot);
    RightSplitter->setStretchFactor(0, 2);
    RightSplitter->setStretchFactor(1, 1);
    RightSplitter->setCollapsible(1, true);
    RightSplitter->setSizes(QList<int>() << 600 << 300);

    m_Splitter = new QSplitter(Qt::Horizontal);
    m_Splitter->addWidget(m_FilterWidget);
    m_Splitter->addWidget(RightSplitter);
    m_Splitter->setStretchFactor(0, 2);
    m_Splitter->setStretchFactor(1, 14);
    m_Splitter->setCollapsible(0, true);

    QVBoxLayout* layout = new QVBoxLayout;
    layout->setContentsMargins(0, 0, 0, 0);
    layout->addWidget(m_Splitter);
    setLayout(layout);

    connect(m_MarketTableView, SIGNAL(clicked(const QModelIndex&)), this, SLOT(OnClicked(const QModelIndex&)));
    connect(m_FilterWidget, &FinTechUI::FilterWidget::FilterChanged, this, &MarketWidget::OnFilterTable, Qt::UniqueConnection);

    // Timer
    m_ReplotTimer = startTimer(500, Qt::PreciseTimer);
}

void MarketWidget::InitFilterWidget()
{
    m_FilterWidget = new FinTechUI::FilterWidget;
    m_FilterWidget->SetHeaderLabels(QStringList() << "机房" << "证券代码");
    m_FilterWidget->SetColumnWidth("机房", 70);
    m_FilterWidget->SetColumnWidth("证券代码", 90);
}

void MarketWidget::InitMarketTableView()
{
    QStringList headerData;
    headerData << "机房" << "交易所" << "证券代码" << "行情序号" << "行情时间" << "最新价" << "成交量" << "涨跌额" << "涨跌幅" << "昨结算价" << "昨收价"
               << "买一价" << "买一量" << "卖一价" << "卖一量" << "开盘价" << "最高价"
               << "最低价" << "涨停价" << "跌停价" << "接收时间";
    m_MarketTableView = new QTableView;
    m_MarketTableView->setEditTriggers(QAbstractItemView::NoEditTriggers);
    m_MarketTableView->setSelectionMode(QAbstractItemView::SingleSelection);
    m_MarketTableView->setSelectionBehavior(QAbstractItemView::SelectRows);
    m_MarketTableView->setSortingEnabled(true);
    m_MarketTableView->horizontalHeader()->setStretchLastSection(true);
    m_MarketTableView->verticalHeader()->hide();
    m_MarketTableModel = new FinTechUI::XTableModel;
    m_MarketProxyModel = new FinTechUI::XSortFilterProxyModel;
    m_MarketProxyModel->setDynamicSortFilter(true);
    m_MarketTableModel->setHeaderLabels(headerData);
    m_MarketProxyModel->setSourceModel(m_MarketTableModel);
    m_MarketTableView->setModel(m_MarketProxyModel);
    m_MarketTableView->sortByColumn(2, Qt::AscendingOrder);
    
    int column = 0;
    m_MarketTableView->setColumnWidth(column++, 80);
    m_MarketTableView->setColumnWidth(column++, 80);
    m_MarketTableView->setColumnWidth(column++, 80);
    m_MarketTableView->setColumnWidth(column++, 70);
    m_MarketTableView->setColumnWidth(column++, 120);
    m_MarketTableView->setColumnWidth(column++, 90);
    m_MarketTableView->setColumnWidth(column++, 70);
    m_MarketTableView->setColumnWidth(column++, 70);
    m_MarketTableView->setColumnWidth(column++, 70);
    m_MarketTableView->setColumnWidth(column++, 80);
    m_MarketTableView->setColumnWidth(column++, 90);
    m_MarketTableView->setColumnWidth(column++, 90);
    m_MarketTableView->setColumnWidth(column++, 90);
    m_MarketTableView->setColumnWidth(column++, 80);
    m_MarketTableView->setColumnWidth(column++, 90);
    m_MarketTableView->setColumnWidth(column++, 80);
    m_MarketTableView->setColumnWidth(column++, 90);
    m_MarketTableView->setColumnWidth(column++, 90);
    m_MarketTableView->setColumnWidth(column++, 110);
    m_MarketTableView->setColumnWidth(column++, 110);
    m_MarketTableView->setColumnWidth(column++, 120);
}

void MarketWidget::InitKCustomPlot()
{
    m_KCustomPlot = new QCustomPlot();
    m_KCustomPlot->addGraph();
    m_KCustomPlot->setBackground(QBrush(QColor("#FFFFFF")));
    m_KCustomPlot->setInteractions(QCP::iRangeDrag | QCP::iRangeZoom | QCP::iSelectPlottables); // 交互模式设置
    // line
    m_KCustomPlot->graph(0)->setPen(QPen(QColor("#237EB3"), 1.2, Qt::SolidLine));
    m_KCustomPlot->graph(0)->setLineStyle((QCPGraph::LineStyle::lsLine));
    // axis
    // m_KCustomPlot->xAxis->setLabel("Tick");
    // m_KCustomPlot->yAxis->setLabel("Price");
    m_KCustomPlot->legend->setVisible(false);
    const QColor axisColor("#46515C");
    m_KCustomPlot->xAxis->setBasePen(QPen(axisColor, 1));
    m_KCustomPlot->xAxis->setTickPen(QPen(axisColor, 1));
    m_KCustomPlot->xAxis->setSubTickPen(QPen(axisColor, 1));
    m_KCustomPlot->xAxis->setTickLabelColor(axisColor);
    m_KCustomPlot->xAxis->setLabelColor(axisColor);
    m_KCustomPlot->yAxis->setBasePen(QPen(axisColor, 1));
    m_KCustomPlot->yAxis->setTickPen(QPen(axisColor, 1));
    m_KCustomPlot->yAxis->setSubTickPen(QPen(axisColor, 1));
    m_KCustomPlot->yAxis->setTickLabelColor(axisColor);
    m_KCustomPlot->yAxis->setLabelColor(axisColor);
    // QCPAxisRect BackGround Color
    m_KCustomPlot->axisRect()->setBackground(QBrush(QColor("#F8FAFC")));
    m_KCustomPlot->axisRect()->setMargins(QMargins(0, 0, 0, 0));
    // Grid
    m_KCustomPlot->xAxis->grid()->setPen(QPen(QColor("#D5DBE1"), 1, Qt::SolidLine));
    m_KCustomPlot->yAxis->grid()->setPen(QPen(QColor("#D5DBE1"), 1, Qt::SolidLine));
    m_KCustomPlot->xAxis->grid()->setSubGridPen(QPen(QColor("#E8ECEF"), 1, Qt::SolidLine));
    m_KCustomPlot->yAxis->grid()->setSubGridPen(QPen(QColor("#E8ECEF"), 1, Qt::SolidLine));
    m_KCustomPlot->xAxis->grid()->setSubGridVisible(true);
    m_KCustomPlot->yAxis->grid()->setSubGridVisible(true);
    // Title
    m_KCustomPlot->plotLayout()->insertRow(0);
    m_TextElement = new QCPTextElement(m_KCustomPlot, "", QFont("sans", 8, QFont::Bold));
    m_TextElement->setTextColor(axisColor);
    m_TextElement->setMargins(QMargins(0, 0, 0, 0));      // 边距设置
    m_TextElement->setLayer("legend");
    m_KCustomPlot->plotLayout()->addElement(0, 0, m_TextElement);
    m_KCustomPlot->setContentsMargins(0, 0, 0, 0);
    m_KCustomPlot->plotLayout()->setRowSpacing(0);
}

void MarketWidget::UpdateFutureData(const Message::PackMessage& data)
{
    if(data.FutureMarketData.Tick < 0)
    {
        return;
    }
    QString Colo = data.FutureMarketData.Colo;
    QString Ticker = data.FutureMarketData.Ticker;
    if(Ticker.isEmpty())
    {
        return;
    }
    QString Key = Colo + ":" + Ticker;
    if(m_ColoTickerModelRowMap.contains(Key))
    {
        UpdateRow(Colo, data.FutureMarketData);
    }
    else
    {
        AppendRow(Colo, data.FutureMarketData);
    }
}

void MarketWidget::UpdateSpotData(const Message::PackMessage& data)
{
    if(data.SpotMarketData.Tick < 0)
    {
        return;
    }
    QString Colo = data.SpotMarketData.Colo;
    QString Ticker = data.SpotMarketData.Ticker;
    if(Ticker.isEmpty())
    {
        return;
    }
    QString Key = Colo + ":" + Ticker;
    if(m_ColoTickerModelRowMap.contains(Key))
    {
        UpdateRow(Colo, data.FutureMarketData);
    }
    else
    {
        AppendRow(Colo, data.FutureMarketData);
    }
}

void MarketWidget::UpdateStockData(const MarketData::TStockMarketData& stock)
{
    if(stock.Tick < 0 || stock.Ticker[0] == '\0')
    {
        return;
    }

    MarketData::TFutureMarketData data = ToTableMarketData(stock);
    QString Colo = data.Colo;
    if(Colo.isEmpty())
    {
        Colo = "本地";
    }
    QString Key = Colo + ":" + data.Ticker;
    if(m_ColoTickerModelRowMap.contains(Key))
    {
        UpdateRow(Colo, data);
    }
    else
    {
        AppendRow(Colo, data);
    }

    m_ColoTickerTickMap[Key].append(data.Tick);
    m_ColoTickerPriceMap[Key].append(data.LastPrice);
    m_ColoTickerMarketDataMap[Key] = data;
}

void MarketWidget::AppendRow(QString Colo, const MarketData::TFutureMarketData& data)
{
    FinTechUI::XTableModelRow* ModelRow = new FinTechUI::XTableModelRow;
    FinTechUI::XTableModelItem* ColoItem = new FinTechUI::XTableModelItem(Colo);
    ModelRow->push_back(ColoItem);
    FinTechUI::XTableModelItem* ExchangeIDItem = new FinTechUI::XTableModelItem(data.ExchangeID);
    ModelRow->push_back(ExchangeIDItem);
    FinTechUI::XTableModelItem* TickerItem = new FinTechUI::XTableModelItem(data.Ticker);
    ModelRow->push_back(TickerItem);
    FinTechUI::XTableModelItem* TickItem = new FinTechUI::XTableModelItem(data.Tick, Qt::AlignRight | Qt::AlignVCenter);
    ModelRow->push_back(TickItem);
    char buffer[32] = {0};
    sprintf(buffer, "%s.%03d000", data.UpdateTime, data.MillSec);
    FinTechUI::XTableModelItem* MarketTimeItem = new FinTechUI::XTableModelItem(buffer);
    ModelRow->push_back(MarketTimeItem);
    sprintf(buffer, "%.3f", data.LastPrice);
    FinTechUI::XTableModelItem* LastPricetem = new FinTechUI::XTableModelItem(buffer, Qt::AlignRight | Qt::AlignVCenter);
    ModelRow->push_back(LastPricetem);
    FinTechUI::XTableModelItem* VolumeItem = new FinTechUI::XTableModelItem(data.Volume, Qt::AlignRight | Qt::AlignVCenter);
    ModelRow->push_back(VolumeItem);

    FinTechUI::XTableModelItem* ChangeItem = new FinTechUI::XTableModelItem(data.LastPrice - data.PreSettlementPrice, Qt::AlignRight | Qt::AlignVCenter);
    ModelRow->push_back(ChangeItem);
    sprintf(buffer, "%.2f%%", (data.LastPrice - data.PreSettlementPrice) / data.PreSettlementPrice * 100);
    FinTechUI::XTableModelItem* ChgItem = new FinTechUI::XTableModelItem(buffer, Qt::AlignRight | Qt::AlignVCenter);
    if(data.LastPrice - data.PreSettlementPrice > 0)
    {
        ChgItem->setForeground(Qt::red);
    }
    else
    {
        ChgItem->setForeground(Qt::green);
    }
    ModelRow->push_back(ChgItem);
    FinTechUI::XTableModelItem* PreSettlementPriceItem = new FinTechUI::XTableModelItem(data.PreSettlementPrice, Qt::AlignRight | Qt::AlignVCenter);
    ModelRow->push_back(PreSettlementPriceItem);
    FinTechUI::XTableModelItem* PreClosePriceItem = new FinTechUI::XTableModelItem(data.PreClosePrice, Qt::AlignRight | Qt::AlignVCenter);
    ModelRow->push_back(PreClosePriceItem);

    sprintf(buffer, "%.3f", data.BidPrice1);
    FinTechUI::XTableModelItem* BidPrice1tem = new FinTechUI::XTableModelItem(buffer, Qt::AlignRight | Qt::AlignVCenter);
    ModelRow->push_back(BidPrice1tem);
    FinTechUI::XTableModelItem* BidVolume1tem = new FinTechUI::XTableModelItem(data.BidVolume1, Qt::AlignRight | Qt::AlignVCenter);
    ModelRow->push_back(BidVolume1tem);
    sprintf(buffer, "%.3f", data.AskPrice1);
    FinTechUI::XTableModelItem* AskPrice1tem = new FinTechUI::XTableModelItem(buffer, Qt::AlignRight | Qt::AlignVCenter);
    ModelRow->push_back(AskPrice1tem);
    FinTechUI::XTableModelItem* AskVolume1tem = new FinTechUI::XTableModelItem(data.AskVolume1, Qt::AlignRight | Qt::AlignVCenter);
    ModelRow->push_back(AskVolume1tem);
    sprintf(buffer, "%.3f", data.OpenPrice);
    FinTechUI::XTableModelItem* OpenPricetem = new FinTechUI::XTableModelItem(buffer, Qt::AlignRight | Qt::AlignVCenter);
    ModelRow->push_back(OpenPricetem);
    sprintf(buffer, "%.3f", data.HighestPrice);
    FinTechUI::XTableModelItem* HighestPricetem = new FinTechUI::XTableModelItem(buffer, Qt::AlignRight | Qt::AlignVCenter);
    ModelRow->push_back(HighestPricetem);
    sprintf(buffer, "%.3f", data.LowestPrice);
    FinTechUI::XTableModelItem* LowestPricetem = new FinTechUI::XTableModelItem(buffer, Qt::AlignRight | Qt::AlignVCenter);
    ModelRow->push_back(LowestPricetem);
    sprintf(buffer, "%.3f", data.UpperLimitPrice);
    FinTechUI::XTableModelItem* UpperLimitPricetem = new FinTechUI::XTableModelItem(buffer, Qt::AlignRight | Qt::AlignVCenter);
    ModelRow->push_back(UpperLimitPricetem);
    sprintf(buffer, "%.3f", data.LowerLimitPrice);
    FinTechUI::XTableModelItem* LowerLimitPricetem = new FinTechUI::XTableModelItem(buffer, Qt::AlignRight | Qt::AlignVCenter);
    ModelRow->push_back(LowerLimitPricetem);
    FinTechUI::XTableModelItem* UpdateTimetem = new FinTechUI::XTableModelItem(data.RecvLocalTime + 11, Qt::AlignLeft | Qt::AlignVCenter);
    ModelRow->push_back(UpdateTimetem);

    FinTechUI::XTableModel::setRowBackgroundColor(ModelRow, QColor("#00CED1"));
    m_MarketTableModel->appendRow(ModelRow);
    QString Ticker = data.Ticker;
    QString Key = Colo + ":" + Ticker;
    m_ColoTickerModelRowMap[Key] = ModelRow;

    bool ok = false;
    QStringList& Tickers = m_ColoTickerSetMap[Colo];
    if(!Tickers.contains(data.Ticker))
    {
        Tickers.append(data.Ticker);
        ok = true;
    }
    if(ok)
    {
        QVector<QMap<QString, QStringList>> data;
        data.append(m_ColoTickerSetMap);
        m_FilterWidget->SetDataRelationMap(data);
    }
}

void MarketWidget::UpdateRow(QString Colo, const MarketData::TFutureMarketData& data)
{
    if(data.Tick < 0)
    {
        return;
    }
    QString Ticker = data.Ticker;
    QString Key = Colo + ":" + Ticker;
    FinTechUI::XTableModelRow* ModelRow = m_ColoTickerModelRowMap[Key];

    (*ModelRow)[3]->setText(data.Tick);
    char buffer[32] = {0};
    sprintf(buffer, "%s.%03d000", data.UpdateTime, data.MillSec);
    (*ModelRow)[4]->setText(buffer);
    sprintf(buffer, "%.3f", data.LastPrice);
    (*ModelRow)[5]->setText(buffer);
    (*ModelRow)[6]->setText(data.Volume);
    (*ModelRow)[7]->setText(data.LastPrice - data.PreSettlementPrice);
    sprintf(buffer, "%.2f%%", (data.LastPrice - data.PreSettlementPrice) / data.PreSettlementPrice * 100);
    (*ModelRow)[8]->setText(buffer);
    if(data.LastPrice - data.PreSettlementPrice > 0)
    {
        (*ModelRow)[8]->setForeground(Qt::red);
    }
    else
    {
        (*ModelRow)[8]->setForeground(Qt::green);
    }
    sprintf(buffer, "%.3f", data.BidPrice1);
    (*ModelRow)[11]->setText(buffer);
    (*ModelRow)[12]->setText(data.BidVolume1);
    sprintf(buffer, "%.3f", data.AskPrice1);
    (*ModelRow)[13]->setText(buffer);
    (*ModelRow)[14]->setText(data.AskVolume1);
    sprintf(buffer, "%.3f", data.HighestPrice);
    (*ModelRow)[16]->setText(buffer);
    sprintf(buffer, "%.3f", data.LowestPrice);
    (*ModelRow)[17]->setText(buffer);
    (*ModelRow)[20]->setText(data.RecvLocalTime + 11);

    m_MarketTableModel->updateRow(ModelRow);
}

void MarketWidget::OnReceivedFutureData(const QList<Message::PackMessage>& items)
{
    for(int i = 0; i < items.size(); i++)
    {
        UpdateFutureData(items.at(i));
        FMTLOG(fmtlog::INF, "MarketWidget::OnReceivedFutureData Ticker:{} Tick:{}", items.at(i).FutureMarketData.Ticker, items.at(i).FutureMarketData.Tick);
        QString Colo = items.at(i).FutureMarketData.Colo;
        QString Ticker = items.at(i).FutureMarketData.Ticker;
        QString Key = Colo + ":" + Ticker;
        QVector<double>& Ticks = m_ColoTickerTickMap[Key];
        Ticks.append(items.at(i).FutureMarketData.Tick);
        QVector<double>& Prices = m_ColoTickerPriceMap[Key];
        Prices.append(items.at(i).FutureMarketData.LastPrice);

        m_ColoTickerMarketDataMap[Key] = items.at(i).FutureMarketData;
    }
}

void MarketWidget::OnReceivedSpotData(const QList<Message::PackMessage>& items)
{
    for(int i = 0; i < items.size(); i++)
    {
        UpdateSpotData(items.at(i));
        FMTLOG(fmtlog::INF, "MarketWidget::OnReceivedSpotData Ticker:{} Tick:{}", items.at(i).FutureMarketData.Ticker, items.at(i).FutureMarketData.Tick);
        QString Colo = items.at(i).FutureMarketData.Colo;
        QString Ticker = items.at(i).FutureMarketData.Ticker;
        QString Key = Colo + ":" + Ticker;
        QVector<double>& Ticks = m_ColoTickerTickMap[Key];
        Ticks.append(items.at(i).FutureMarketData.Tick);
        QVector<double>& Prices = m_ColoTickerPriceMap[Key];
        Prices.append(items.at(i).FutureMarketData.LastPrice);

        m_ColoTickerMarketDataMap[Key] = items.at(i).FutureMarketData;
    }
}

void MarketWidget::OnReceivedStockData(const QList<Message::PackMessage>& items)
{
    for(int i = 0; i < items.size(); i++)
    {
        const MarketData::TStockMarketData& data = items.at(i).StockMarketData;
        UpdateStockData(data);
        FMTLOG(fmtlog::INF, "MarketWidget::OnReceivedStockData Ticker:{} Tick:{} Rows:{}",
               data.Ticker, data.Tick, m_MarketTableModel->rowCount());
    }
}

void MarketWidget::OnFilterTable(const QVector<QStringList>& filter)
{
    QStringList ColoFilter = filter.at(0);
    QStringList TickerFilter = filter.at(1);
    QMap<int, QStringList> FilterMap;
    FilterMap[0] = ColoFilter;
    FilterMap[2] = TickerFilter;
    m_MarketProxyModel->setRowFilter(FilterMap);
    m_MarketProxyModel->resetFilter();
}

void MarketWidget::OnClicked(const QModelIndex& index)
{
    int row = index.row();
    QString Colo = m_MarketProxyModel->index(row, 0).data().toString();
    QString Ticker = m_MarketProxyModel->index(row, 2).data().toString();
    m_TextElement->setText(Ticker);
    
    QString Key = Colo + ":" + Ticker;
    QVector<double>& Ticks = m_ColoTickerTickMap[Key];
    QVector<double>& Prices = m_ColoTickerPriceMap[Key];
    MarketData::TFutureMarketData& data = m_ColoTickerMarketDataMap[Key];
    // replot CustomPlot
    m_KCustomPlot->xAxis->setRange(0, data.TotalTick);
    m_KCustomPlot->yAxis->setRange(data.LowestPrice - 10, data.HighestPrice + 10);
    m_KCustomPlot->graph(0)->setData(Ticks, Prices);
    m_KCustomPlot->replot(QCustomPlot::rpQueuedReplot);
}

void MarketWidget::timerEvent(QTimerEvent *event)
{
    // Replot every 200ms
    if(event->timerId() == m_ReplotTimer)
    {
        if(m_MarketProxyModel->rowCount() == 0)
        {
            return;
        }

        int row = m_MarketTableView->currentIndex().row();
        if(row < 0)
        {
            row = 0;
        }
        QString Colo = m_MarketProxyModel->index(row, 0).data().toString();
        QString Ticker = m_MarketProxyModel->index(row, 2).data().toString();
        m_TextElement->setText(Ticker);

        QString Key = Colo + ":" + Ticker;
        QVector<double>& Ticks = m_ColoTickerTickMap[Key];
        QVector<double>& Prices = m_ColoTickerPriceMap[Key];
        MarketData::TFutureMarketData& data = m_ColoTickerMarketDataMap[Key];
        // replot CustomPlot
        m_KCustomPlot->xAxis->setRange(0, data.TotalTick);
        m_KCustomPlot->yAxis->setRange(data.LowestPrice - 10, data.HighestPrice + 10);
        m_KCustomPlot->graph(0)->setData(Ticks, Prices);
        m_KCustomPlot->replot(QCustomPlot::rpQueuedReplot);
    }
}
