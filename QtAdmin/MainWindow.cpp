#include "MainWindow.hpp"

#include <QDialog>
#include <QDialogButtonBox>
#include <QAbstractItemView>
#include <QFormLayout>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QPushButton>
#include <QTableWidget>
#include <QTabWidget>
#include <QToolBar>
#include <QVBoxLayout>
#include <QWidget>

namespace
{
QTableWidget* makeTable(const QStringList& headers, QWidget* parent)
{
    auto* table = new QTableWidget(parent);
    table->setColumnCount(headers.size());
    table->setHorizontalHeaderLabels(headers);
    table->setEditTriggers(QAbstractItemView::NoEditTriggers);
    table->setSelectionBehavior(QAbstractItemView::SelectRows);
    table->setSelectionMode(QAbstractItemView::SingleSelection);
    table->horizontalHeader()->setStretchLastSection(true);
    return table;
}

QJsonObject dialogValues(QWidget* parent, const QString& title,
                         const QList<QPair<QString, QString>>& fields)
{
    QDialog dialog(parent);
    dialog.setWindowTitle(title);
    auto* layout = new QFormLayout(&dialog);
    QList<QLineEdit*> inputs;
    for(const auto& field : fields)
    {
        auto* input = new QLineEdit(&dialog);
        layout->addRow(field.first, input);
        inputs.append(input);
    }
    auto* buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dialog);
    layout->addRow(buttons);
    QObject::connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
    QObject::connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    if(dialog.exec() != QDialog::Accepted)
    {
        return {};
    }
    QJsonObject values;
    for(int index = 0; index < fields.size(); ++index)
    {
        if(inputs[index]->text().trimmed().isEmpty())
        {
            QMessageBox::warning(parent, title, QStringLiteral("所有字段均为必填项。"));
            return {};
        }
        values.insert(fields[index].second, inputs[index]->text().trimmed());
    }
    return values;
}
}

MainWindow::MainWindow(QWidget* parent) : QMainWindow(parent)
{
    setWindowTitle(QStringLiteral("QuantFabric 管理端"));
    resize(1180, 760);
    createLoginPage();
}

void MainWindow::createLoginPage()
{
    auto* page = new QWidget(this);
    auto* layout = new QVBoxLayout(page);
    layout->setContentsMargins(120, 100, 120, 100);
    auto* form = new QFormLayout;
    m_serviceUrlEdit = new QLineEdit(QStringLiteral("http://127.0.0.1:18080"), page);
    m_usernameEdit = new QLineEdit(page);
    m_passwordEdit = new QLineEdit(page);
    m_passwordEdit->setEchoMode(QLineEdit::Password);
    form->addRow(QStringLiteral("权限服务地址"), m_serviceUrlEdit);
    form->addRow(QStringLiteral("用户名"), m_usernameEdit);
    form->addRow(QStringLiteral("密码"), m_passwordEdit);
    layout->addWidget(new QLabel(QStringLiteral("QuantFabric 权限管理"), page));
    layout->addLayout(form);
    auto* button = new QPushButton(QStringLiteral("登录"), page);
    layout->addWidget(button);
    layout->addStretch();
    setCentralWidget(page);
    connect(button, &QPushButton::clicked, this, [this] { login(); });
    connect(m_passwordEdit, &QLineEdit::returnPressed, this, [this] { login(); });
}

void MainWindow::login()
{
    m_serviceUrl = m_serviceUrlEdit->text().trimmed();
    while(m_serviceUrl.endsWith('/'))
    {
        m_serviceUrl.chop(1);
    }
    const QJsonObject payload{{"username", m_usernameEdit->text().trimmed()},
                              {"password", m_passwordEdit->text()}};
    request("POST", QStringLiteral("/v1/sessions/development"), QJsonDocument(payload),
            [this](const QJsonDocument& document) {
                m_sessionId = document.object().value("session_id").toString();
                if(m_sessionId.isEmpty())
                {
                    QMessageBox::warning(this, QStringLiteral("登录失败"), QStringLiteral("服务没有返回有效会话。"));
                    return;
                }
                createAdminPages();
                refreshAll();
            });
}

void MainWindow::createAdminPages()
{
    m_tabs = new QTabWidget(this);
    m_identities = makeTable({QStringLiteral("主体"), QStringLiteral("用户名"), QStringLiteral("显示名"), QStringLiteral("启用")}, m_tabs);
    m_menus = makeTable({QStringLiteral("菜单"), QStringLiteral("名称"), QStringLiteral("父菜单"), QStringLiteral("资源"), QStringLiteral("动作"), QStringLiteral("排序"), QStringLiteral("启用")}, m_tabs);
    m_roleBindings = makeTable({QStringLiteral("用户/主体"), QStringLiteral("角色"), QStringLiteral("域")}, m_tabs);
    m_accountGrants = makeTable({QStringLiteral("编号"), QStringLiteral("用户/角色"), QStringLiteral("域"), QStringLiteral("账户"), QStringLiteral("动作"), QStringLiteral("启用")}, m_tabs);
    m_audit = makeTable({QStringLiteral("时间"), QStringLiteral("主体"), QStringLiteral("动作"), QStringLiteral("资源"), QStringLiteral("结果"), QStringLiteral("跟踪号")}, m_tabs);
    m_tabs->addTab(m_identities, QStringLiteral("用户"));
    m_tabs->addTab(m_menus, QStringLiteral("菜单"));
    m_tabs->addTab(m_roleBindings, QStringLiteral("角色"));
    m_tabs->addTab(m_accountGrants, QStringLiteral("账户授权"));
    m_tabs->addTab(m_audit, QStringLiteral("审计"));
    setCentralWidget(m_tabs);

    auto* toolbar = addToolBar(QStringLiteral("管理"));
    auto* refresh = toolbar->addAction(QStringLiteral("刷新"));
    auto* addUser = toolbar->addAction(QStringLiteral("新增用户"));
    auto* addMenu = toolbar->addAction(QStringLiteral("新增菜单"));
    auto* addRole = toolbar->addAction(QStringLiteral("绑定角色"));
    auto* addGrant = toolbar->addAction(QStringLiteral("账户授权"));
    connect(refresh, &QAction::triggered, this, [this] { refreshAll(); });
    connect(addUser, &QAction::triggered, this, [this] { createIdentity(); });
    connect(addMenu, &QAction::triggered, this, [this] { createMenu(); });
    connect(addRole, &QAction::triggered, this, [this] { createRoleBinding(); });
    connect(addGrant, &QAction::triggered, this, [this] { createAccountGrant(); });
}

void MainWindow::request(const QByteArray& method, const QString& path, const QJsonDocument& body,
                         const std::function<void(const QJsonDocument&)>& onSuccess)
{
    QNetworkRequest request(QUrl(m_serviceUrl + path));
    request.setHeader(QNetworkRequest::ContentTypeHeader, QStringLiteral("application/json"));
    if(!m_sessionId.isEmpty())
    {
        request.setRawHeader("X-QF-Session-ID", m_sessionId.toUtf8());
    }
    QNetworkReply* reply = nullptr;
    if(method == "GET")
    {
        reply = m_network.get(request);
    }
    else if(method == "PUT")
    {
        reply = m_network.put(request, body.toJson(QJsonDocument::Compact));
    }
    else
    {
        reply = m_network.post(request, body.toJson(QJsonDocument::Compact));
    }
    connect(reply, &QNetworkReply::finished, this, [this, reply, onSuccess] {
        const QByteArray payload = reply->readAll();
        const auto error = reply->error();
        reply->deleteLater();
        if(error != QNetworkReply::NoError)
        {
            QMessageBox::warning(this, QStringLiteral("请求失败"), QString::fromUtf8(payload));
            return;
        }
        const QJsonDocument document = QJsonDocument::fromJson(payload);
        if(document.isNull())
        {
            QMessageBox::warning(this, QStringLiteral("响应错误"), QStringLiteral("服务返回了无效 JSON。"));
            return;
        }
        onSuccess(document);
    });
}

void MainWindow::populateTable(QTableWidget* table, const QJsonArray& items, const QStringList& fields)
{
    table->setRowCount(items.size());
    for(int row = 0; row < items.size(); ++row)
    {
        const QJsonObject object = items[row].toObject();
        for(int column = 0; column < fields.size(); ++column)
        {
            const QJsonValue value = object.value(fields[column]);
            const QString text = value.isBool() ? (value.toBool() ? QStringLiteral("是") : QStringLiteral("否")) :
                                 value.isDouble() ? QString::number(value.toDouble()) : value.toString();
            table->setItem(row, column, new QTableWidgetItem(text));
        }
    }
}

void MainWindow::refreshAll()
{
    refreshIdentities();
    refreshMenus();
    refreshRoleBindings();
    refreshAccountGrants();
    refreshAudit();
}

void MainWindow::refreshIdentities()
{
    request("GET", QStringLiteral("/v1/admin/identities"), {}, [this](const QJsonDocument& doc) {
        populateTable(m_identities, doc.array(), {"subject", "username", "display_name", "active"});
    });
}

void MainWindow::refreshMenus()
{
    request("GET", QStringLiteral("/v1/admin/menus"), {}, [this](const QJsonDocument& doc) {
        populateTable(m_menus, doc.array(), {"id", "name", "parent_id", "resource", "action", "sort_order", "enabled"});
    });
}

void MainWindow::refreshRoleBindings()
{
    request("GET", QStringLiteral("/v1/admin/role-bindings"), {}, [this](const QJsonDocument& doc) {
        m_roleBindings->setRowCount(0);
        const QJsonArray items = doc.object().value("items").toArray();
        m_roleBindings->setRowCount(items.size());
        for(int row = 0; row < items.size(); ++row)
        {
            const QJsonArray item = items[row].toArray();
            for(int column = 0; column < item.size(); ++column)
            {
                m_roleBindings->setItem(row, column, new QTableWidgetItem(item[column].toString()));
            }
        }
    });
}

void MainWindow::refreshAccountGrants()
{
    request("GET", QStringLiteral("/v1/admin/account-grants"), {}, [this](const QJsonDocument& doc) {
        populateTable(m_accountGrants, doc.array(), {"id", "subject", "domain", "account", "action", "active"});
    });
}

void MainWindow::refreshAudit()
{
    request("POST", QStringLiteral("/v1/admin/audit/query"), QJsonDocument(QJsonObject{{"limit", 100}}),
            [this](const QJsonDocument& doc) {
                const QJsonArray items = doc.object().value("items").toArray();
                m_audit->setRowCount(items.size());
                for(int row = 0; row < items.size(); ++row)
                {
                    const QJsonObject item = items[row].toObject();
                    const QStringList fields{"created_at", "actor", "action", "resource", "result", "trace_id"};
                    for(int column = 0; column < fields.size(); ++column)
                    {
                        m_audit->setItem(row, column, new QTableWidgetItem(item.value(fields[column]).toVariant().toString()));
                    }
                }
            });
}

void MainWindow::createIdentity()
{
    const QJsonObject values = dialogValues(this, QStringLiteral("新增用户"), {
        {QStringLiteral("用户名"), "username"}, {QStringLiteral("显示名"), "display_name"}, {QStringLiteral("初始密码"), "password"},
    });
    if(values.isEmpty()) return;
    request("POST", QStringLiteral("/v1/admin/identities"), QJsonDocument(values), [this](const QJsonDocument&) { refreshIdentities(); });
}

void MainWindow::createMenu()
{
    QJsonObject values = dialogValues(this, QStringLiteral("新增菜单"), {
        {QStringLiteral("菜单标识"), "id"}, {QStringLiteral("名称"), "name"}, {QStringLiteral("资源"), "resource"}, {QStringLiteral("动作"), "action"},
    });
    if(values.isEmpty()) return;
    values.insert("sort_order", 0);
    values.insert("enabled", true);
    request("PUT", QStringLiteral("/v1/admin/menus/") + values.value("id").toString(), QJsonDocument(values),
            [this](const QJsonDocument&) { refreshMenus(); });
}

void MainWindow::createRoleBinding()
{
    const QJsonObject values = dialogValues(this, QStringLiteral("绑定角色"), {
        {QStringLiteral("主体"), "subject"}, {QStringLiteral("角色"), "role"}, {QStringLiteral("业务域"), "domain"},
    });
    if(values.isEmpty()) return;
    request("POST", QStringLiteral("/v1/admin/role-bindings"), QJsonDocument(values),
            [this](const QJsonDocument&) { refreshRoleBindings(); });
}

void MainWindow::createAccountGrant()
{
    const QJsonObject values = dialogValues(this, QStringLiteral("账户授权"), {
        {QStringLiteral("主体或角色"), "subject"}, {QStringLiteral("业务域"), "domain"},
        {QStringLiteral("资金账户"), "account"}, {QStringLiteral("动作"), "action"},
    });
    if(values.isEmpty()) return;
    request("POST", QStringLiteral("/v1/admin/account-grants"), QJsonDocument(values),
            [this](const QJsonDocument&) { refreshAccountGrants(); });
}
