#include <QApplication>
#include <QFont>

#include "MainWindow.hpp"

int main(int argc, char* argv[])
{
    QApplication application(argc, argv);
    // QtAdmin 与 vn.py 工作台统一使用本机已安装的中文字体，避免标题和表格出现乱码。
    application.setFont(QFont(QStringLiteral("Noto Sans CJK SC"), 10));
    MainWindow window;
    window.show();
    return application.exec();
}
