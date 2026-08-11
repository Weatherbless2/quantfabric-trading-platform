#include <algorithm>
#include <cstring>
#include <string>

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "QuantFabricClient.hpp"

namespace py = pybind11;

namespace
{
template <size_t N>
py::str Text(const char (&value)[N])
{
    const size_t length = std::find(value, value + N, '\0') - value;
    // External SDKs can place non-UTF-8 bytes in fixed C arrays. Replace only
    // invalid byte sequences at the Python boundary so one log cannot break
    // the complete vn.py event loop.
    return py::reinterpret_steal<py::str>(
        PyUnicode_DecodeUTF8(value, static_cast<Py_ssize_t>(length), "replace"));
}

std::string OrderStatusName(uint8_t status)
{
    switch(status)
    {
    case Message::EOrderStatusType::EORDER_SENDED: return "submitting";
    case Message::EOrderStatusType::EBROKER_ACK:
    case Message::EOrderStatusType::EEXCHANGE_ACK: return "accepted";
    case Message::EOrderStatusType::EPARTTRADED: return "partial";
    case Message::EOrderStatusType::EALLTRADED: return "filled";
    case Message::EOrderStatusType::ECANCELLING: return "cancelling";
    case Message::EOrderStatusType::ECANCELLED: return "cancelled";
    case Message::EOrderStatusType::EPARTTRADED_CANCELLED: return "partial_cancelled";
    default: return "rejected";
    }
}

py::dict ToPython(const Message::PackMessage& message)
{
    py::dict result;
    switch(message.MessageType)
    {
    case Message::EMessageType::ELoginResponse:
        result["type"] = "login";
        result["connected"] = message.LoginResponse.ErrorID == 0;
        result["error_id"] = message.LoginResponse.ErrorID;
        result["error"] = Text(message.LoginResponse.ErrorMsg);
        break;
    case Message::EMessageType::EStockMarketData:
    {
        const auto& data = message.StockMarketData;
        result["type"] = "stock_quote";
        result["ticker"] = Text(data.Ticker);
        result["exchange"] = Text(data.ExchangeID);
        result["update_time"] = Text(data.UpdateTime);
        result["millisec"] = data.MillSec;
        result["last_price"] = data.LastPrice;
        result["volume"] = data.Volume;
        result["turnover"] = data.Turnover;
        result["pre_close"] = data.PreClosePrice;
        result["open"] = data.OpenPrice;
        result["high"] = data.HighestPrice;
        result["low"] = data.LowestPrice;
        result["bid_prices"] = std::vector<double>(data.BidPrice, data.BidPrice + 5);
        result["ask_prices"] = std::vector<double>(data.AskPrice, data.AskPrice + 5);
        result["bid_volumes"] = std::vector<int>(data.BidVolume, data.BidVolume + 5);
        result["ask_volumes"] = std::vector<int>(data.AskVolume, data.AskVolume + 5);
        break;
    }
    case Message::EMessageType::EAccountFund:
        result["type"] = "fund";
        result["account"] = Text(message.AccountFund.Account);
        result["balance"] = message.AccountFund.Balance;
        result["available"] = message.AccountFund.Available;
        result["update_time"] = Text(message.AccountFund.UpdateTime);
        break;
    case Message::EMessageType::EAccountPosition:
        result["type"] = "position";
        result["account"] = Text(message.AccountPosition.Account);
        result["ticker"] = Text(message.AccountPosition.Ticker);
        result["exchange"] = Text(message.AccountPosition.ExchangeID);
        result["total"] = message.AccountPosition.StockPosition.LongPosition;
        result["available"] = message.AccountPosition.StockPosition.LongYdPosition;
        result["yesterday"] = message.AccountPosition.StockPosition.LongYdPosition;
        result["update_time"] = Text(message.AccountPosition.UpdateTime);
        break;
    case Message::EMessageType::EOrderStatus:
    {
        const auto& data = message.OrderStatus;
        result["type"] = "order_status";
        result["ticker"] = Text(data.Ticker);
        result["exchange"] = Text(data.ExchangeID);
        result["order_ref"] = Text(data.OrderRef);
        result["order_sys_id"] = Text(data.OrderSysID);
        result["order_token"] = data.OrderToken;
        result["side"] = data.OrderSide == Message::EOrderSide::EOPEN_LONG ? 1 : 2;
        result["price"] = data.SendPrice;
        result["volume"] = data.SendVolume;
        result["traded"] = data.TotalTradedVolume;
        result["status"] = OrderStatusName(data.OrderStatus);
        result["error_id"] = data.ErrorID;
        result["error"] = Text(data.ErrorMsg);
        result["update_time"] = Text(data.UpdateTime);
        break;
    }
    case Message::EMessageType::EEventLog:
        result["type"] = "event_log";
        result["level"] = message.EventLog.Level;
        result["app"] = Text(message.EventLog.App);
        result["message"] = Text(message.EventLog.Event);
        break;
    default:
        result["type"] = "other";
        result["message_type"] = message.MessageType;
        break;
    }
    return result;
}
}

PYBIND11_MODULE(quantfabric_native, module)
{
    module.doc() = "Native QuantFabric XServer client for the vn.py workbench.";

    py::class_<QuantFabricClient>(module, "QuantFabricClient")
        .def(py::init<std::string, unsigned int, std::string, std::string,
                      std::string, std::string, std::string, std::string>(),
             py::arg("host") = "127.0.0.1", py::arg("port") = 8000,
             py::arg("user") = "admin", py::arg("password") = "123456",
             py::arg("session_id") = "",
             py::arg("colo") = "LocalTest", py::arg("product") = "ATPTest",
             py::arg("account") = "610000071840")
        .def("start", &QuantFabricClient::Start)
        .def("reconnect", &QuantFabricClient::Reconnect)
        .def("login", &QuantFabricClient::Login)
        .def("stop", &QuantFabricClient::Stop)
        .def("is_connected", &QuantFabricClient::IsConnected)
        .def("is_logged_in", &QuantFabricClient::IsLoggedIn)
        .def("subscribe", &QuantFabricClient::Subscribe)
        .def("send_order", &QuantFabricClient::SendOrder)
        .def("cancel_order", &QuantFabricClient::CancelOrder)
        .def("poll", [](QuantFabricClient& client) {
            py::list messages;
            for(const Message::PackMessage& message : client.DrainMessages())
            {
                messages.append(ToPython(message));
            }
            return messages;
        })
        .def_property_readonly("last_error", &QuantFabricClient::LastError);
}
