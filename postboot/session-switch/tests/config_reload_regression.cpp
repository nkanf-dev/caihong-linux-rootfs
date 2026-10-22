// SPDX-License-Identifier: GPL-2.0-or-later
// Link the unmodified or patched real SDDM ConfigReader.cpp; do not copy its parser.
#include "ConfigReader.h"

#include <QtCore/QCoreApplication>
#include <QtCore/QDir>
#include <QtCore/QFile>
#include <QtCore/QTemporaryDir>
#include <QtCore/QTextStream>
#include <cerrno>
#include <cstring>
#include <functional>
#include <stdexcept>
#include <string>
#include <utility>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>

static void require(bool ok, const char *message)
{
    if (!ok)
        throw std::runtime_error(message);
}

static void writeFile(const QString &path, const QByteArray &contents)
{
    QFile file(path);
    require(file.open(QIODevice::WriteOnly | QIODevice::Truncate), "open fixture file");
    require(file.write(contents) == contents.size(), "write fixture file");
    require(file.flush(), "flush fixture file");
}

static void stamp(const QString &path, time_t seconds)
{
    const struct timespec times[2] = {{seconds, 123000000}, {seconds, 123000000}};
    if (utimensat(AT_FDCWD, QFile::encodeName(path).constData(), times, 0) != 0)
        throw std::runtime_error(std::string("utimensat: ") + std::strerror(errno));
}

class TestConfig : public SDDM::ConfigBase, public SDDM::ConfigSection {
public:
    SDDM::ConfigEntry<QString> Session{this, QStringLiteral("Session"), QStringLiteral("default.desktop"), QString()};
    SDDM::ConfigEntry<bool> Relogin{this, QStringLiteral("Relogin"), false, QString()};
    TestConfig(const QString &file, const QString &dir, const QString &sys)
        : SDDM::ConfigBase(file, dir, sys), SDDM::ConfigSection(this, QStringLiteral("Autologin"))
    {
        load();
    }
};

struct Fixture {
    QTemporaryDir root;
    QString systemDir;
    QString localDir;
    QString mainFile;
    QString baseFile;
    QString overrideFile;
    static constexpr time_t past = 1700000000;
    static constexpr time_t future = 2000000000;
    Fixture()
    {
        require(root.isValid(), "temporary directory");
        systemDir = root.path() + QStringLiteral("/system");
        localDir = root.path() + QStringLiteral("/local");
        mainFile = root.path() + QStringLiteral("/sddm.conf");
        baseFile = systemDir + QStringLiteral("/holo.conf");
        overrideFile = localDir + QStringLiteral("/zzt-holo-temp-login.conf");
        require(QDir().mkpath(systemDir) && QDir().mkpath(localDir), "fixture directories");
        writeFile(baseFile, "[Autologin]\nSession=game.desktop\nRelogin=true\n");
        stamp(baseFile, past);
        stamp(systemDir, past);
        stamp(localDir, past);
    }
    TestConfig config() { return TestConfig(mainFile, localDir, systemDir); }
};

static void unchangedLoad()
{
    Fixture f;
    auto c = f.config();
    c.load();
    c.load();
    require(c.Session.get() == QStringLiteral("game.desktop"), "unchanged load session");
    require(c.Relogin.get(), "unchanged load relogin");
}

static void futureDirectoryThenNewFile()
{
    Fixture f;
    stamp(f.localDir, Fixture::future);
    auto c = f.config();
    require(c.Session.get() == QStringLiteral("game.desktop"), "initial game session");
    writeFile(f.overrideFile, "[Autologin]\nSession=desk.desktop\n");
    stamp(f.overrideFile, Fixture::past + 1);
    stamp(f.localDir, Fixture::past + 1); // The wall clock is behind the cached directory mtime.
    c.load();
    require(c.Session.get() == QStringLiteral("desk.desktop"), "reload new file after future directory");
}

static void existingFileClockRollback()
{
    Fixture f;
    writeFile(f.overrideFile, "[Autologin]\nSession=desk.desktop\n");
    stamp(f.overrideFile, Fixture::future);
    stamp(f.localDir, Fixture::future);
    auto c = f.config();
    writeFile(f.overrideFile, "[Autologin]\nSession=next.desktop\n");
    stamp(f.overrideFile, Fixture::past + 1);
    stamp(f.localDir, Fixture::past + 1);
    c.load();
    require(c.Session.get() == QStringLiteral("next.desktop"), "reload existing file after clock rollback");
}

static void deletedFutureFile()
{
    Fixture f;
    writeFile(f.overrideFile, "[Autologin]\nSession=desk.desktop\n");
    stamp(f.overrideFile, Fixture::future);
    stamp(f.localDir, Fixture::future);
    auto c = f.config();
    require(c.Session.get() == QStringLiteral("desk.desktop"), "initial temporary desktop");
    require(QFile::remove(f.overrideFile), "remove future file");
    stamp(f.localDir, Fixture::past + 1);
    c.load();
    require(c.Session.get() == QStringLiteral("game.desktop"), "reload after future file deletion");
}

static void sameTimestampSameSizeReplacement()
{
    Fixture f;
    writeFile(f.overrideFile, "[Autologin]\nSession=desk.desktop\n");
    stamp(f.overrideFile, Fixture::past + 1);
    stamp(f.localDir, Fixture::past + 1);
    auto c = f.config();
    const QString replacement = f.localDir + QStringLiteral("/replacement.tmp");
    writeFile(replacement, "[Autologin]\nSession=next.desktop\n");
    require(QFile::remove(f.overrideFile), "remove old override");
    require(QFile::rename(replacement, f.overrideFile), "replace override");
    stamp(f.overrideFile, Fixture::past + 1);
    stamp(f.localDir, Fixture::past + 1);
    c.load();
    require(c.Session.get() == QStringLiteral("next.desktop"), "same time and size replacement");
}

static void removedKeyReturnsToLowerLayer()
{
    Fixture f;
    writeFile(f.overrideFile, "[Autologin]\nSession=desk.desktop\nRelogin=false\n");
    stamp(f.overrideFile, Fixture::past + 1);
    stamp(f.localDir, Fixture::past + 1);
    auto c = f.config();
    writeFile(f.overrideFile, "[Autologin]\nRelogin=false\n");
    stamp(f.overrideFile, Fixture::future);
    stamp(f.localDir, Fixture::future);
    c.load();
    require(c.Session.get() == QStringLiteral("game.desktop"), "removed key returns to lower layer");
    require(!c.Relogin.get(), "remaining key retains local precedence");
}

static void removedLastKeyReturnsToDefault()
{
    Fixture f;
    require(QFile::remove(f.baseFile), "remove base fixture");
    writeFile(f.overrideFile, "[Autologin]\nSession=desk.desktop\nRelogin=true\n");
    stamp(f.overrideFile, Fixture::past + 1);
    stamp(f.localDir, Fixture::past + 1);
    auto c = f.config();
    writeFile(f.overrideFile, "[Autologin]\n# all settings removed\n");
    stamp(f.overrideFile, Fixture::future);
    stamp(f.localDir, Fixture::future);
    c.load();
    require(c.Session.get() == QStringLiteral("default.desktop"), "removed key returns to default");
    require(!c.Relogin.get(), "removed bool returns to default");
}

static void precedenceAndUnknownEntries()
{
    Fixture f;
    writeFile(f.localDir + QStringLiteral("/aa.conf"), "[Autologin]\nSession=aa.desktop\n");
    writeFile(f.localDir + QStringLiteral("/zz.conf"), "[Autologin]\nSession=zz.desktop\n");
    auto c = f.config();
    require(c.Session.get() == QStringLiteral("zz.desktop"), "local alphabetic order over system layer");
    writeFile(f.mainFile, "[Autologin]\nSession=main.desktop\nUnknown=value\n[UnknownSection]\nUnknown=value\n");
    c.load();
    require(c.Session.get() == QStringLiteral("main.desktop"), "single file has final precedence");
    require(c.hasUnused(), "unknown entries remain detectable");
    writeFile(f.mainFile, "[Autologin]\nSession=main.desktop\n");
    c.load();
    require(!c.hasUnused(), "unknown-entry flag describes current files");
}

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    const std::pair<const char *, std::function<void()>> cases[] = {
        {"unchanged_load", unchangedLoad},
        {"future_directory_new_file", futureDirectoryThenNewFile},
        {"existing_file_clock_rollback", existingFileClockRollback},
        {"deleted_future_file", deletedFutureFile},
        {"same_time_same_size_replacement", sameTimestampSameSizeReplacement},
        {"removed_key_lower_layer", removedKeyReturnsToLowerLayer},
        {"removed_last_key_defaults", removedLastKeyReturnsToDefault},
        {"precedence_unknown_entries", precedenceAndUnknownEntries},
    };
    int failed = 0;
    for (const auto &test : cases) {
        try {
            test.second();
            QTextStream(stdout) << "PASS " << test.first << Qt::endl;
        } catch (const std::exception &error) {
            ++failed;
            QTextStream(stderr) << "FAIL " << test.first << ": " << error.what() << Qt::endl;
        }
    }
    return failed == 0 ? 0 : 1;
}
