#include <QApplication>
#include <QColor>
#include <QFile>
#include <QPalette>
#include <QStyleFactory>
#include <QTextStream>
#include <stdio.h>
#include "FMTLogger.hpp"
#include "MainWindow.h"

namespace
{
QPalette CreateApplicationPalette()
{
    QPalette palette;
    palette.setColor(QPalette::Window, QColor("#F1F3F5"));
    palette.setColor(QPalette::WindowText, QColor("#20262E"));
    palette.setColor(QPalette::Base, QColor("#FFFFFF"));
    palette.setColor(QPalette::AlternateBase, QColor("#F6F8FA"));
    palette.setColor(QPalette::ToolTipBase, QColor("#FFFFFF"));
    palette.setColor(QPalette::ToolTipText, QColor("#20262E"));
    palette.setColor(QPalette::Text, QColor("#20262E"));
    palette.setColor(QPalette::Button, QColor("#E5E9ED"));
    palette.setColor(QPalette::ButtonText, QColor("#20262E"));
    palette.setColor(QPalette::BrightText, QColor("#FFFFFF"));
    palette.setColor(QPalette::Highlight, QColor("#237EB3"));
    palette.setColor(QPalette::HighlightedText, QColor("#FFFFFF"));
    return palette;
}
}

void printHelp()
{
    printf("Usage: QtTrader -f ~/config.yml -d\n");
    printf("\t-f: Config File Path\n");
    printf("\t-a: Account\n");
    printf("\t-d: log debug mode, print debug log\n");
    printf("\t-h: print help infomartion\n");
}

int main(int argc, char *argv[])
{
    std::string configPath = "./XMonitor.yml";
    int ch;
    bool debug = false;
    while ((ch = getopt(argc, argv, "f:a:dh")) != -1)
    {
        switch (ch)
        {
        case 'f':
            configPath = optarg;
            break;
        case 'a':
            break;
        case 'd':
            debug = true;
            break;
        case 'h':
        case '?':
        case ':':
        default:
            printHelp();
            exit(-1);
            break;
        }
    }
    std::string app_log_path;
    char* p = getenv("APP_LOG_PATH");
    if(p == NULL)
    {
        app_log_path = "./log/";
    }
    else
    {
        app_log_path = p;
    }
    std::string cmd;
    for(int i = 0; i < argc; i++)
    {
        cmd += (std::string(argv[i]) + " ");
    }
    FMTLog::Logger::Init(app_log_path, "QtTrader");
    FMTLog::Logger::SetDebugLevel(debug);
    FMTLOG(fmtlog::INF, cmd);
    FMTLOG(fmtlog::INF, "QtTrader AppCommitID:{} BranchName:{}", APP_COMMIT_ID, APP_BRANCH_NAME);

    QApplication a(argc, argv);
    QApplication::setStyle(QStyleFactory::create("Fusion"));
    qApp->setPalette(CreateApplicationPalette());

    MainWindow w(configPath);
    w.show();

    return a.exec();
}
