#ifndef QTADMIN_MAINWINDOW_HPP
#define QTADMIN_MAINWINDOW_HPP

#include <QMainWindow>
#include <QNetworkAccessManager>
#include <QString>

#include <functional>

class QJsonArray;
class QJsonDocument;
class QLineEdit;
class QTableWidget;
class QTabWidget;

class MainWindow final : public QMainWindow
{
public:
    explicit MainWindow(QWidget* parent = nullptr);

private:
    void createLoginPage();
    void createAdminPages();
    void login();
    void refreshAll();
    void refreshIdentities();
    void refreshMenus();
    void refreshRoleBindings();
    void refreshPolicies();
    void refreshAccountGrants();
    void refreshAudit();
    void createIdentity();
    void createMenu();
    void createRoleBinding();
    void createPolicy();
    void createAccountGrant();
    void request(const QByteArray& method, const QString& path, const QJsonDocument& body,
                 const std::function<void(const QJsonDocument&)>& onSuccess);
    void populateTable(QTableWidget* table, const QJsonArray& items, const QStringList& fields);

    QNetworkAccessManager m_network;
    QString m_serviceUrl;
    QString m_sessionId;
    QLineEdit* m_serviceUrlEdit = nullptr;
    QLineEdit* m_usernameEdit = nullptr;
    QLineEdit* m_passwordEdit = nullptr;
    QTabWidget* m_tabs = nullptr;
    QTableWidget* m_identities = nullptr;
    QTableWidget* m_menus = nullptr;
    QTableWidget* m_roleBindings = nullptr;
    QTableWidget* m_policies = nullptr;
    QTableWidget* m_accountGrants = nullptr;
    QTableWidget* m_audit = nullptr;
};

#endif
