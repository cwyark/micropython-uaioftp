import uos as os
import usocket as _socket
import uasyncio as asyncio
import uerrno
import time
import sys

try:
    import logging
except:

    class logging(object):
        def __init__(self, *args):
            pass

        @staticmethod
        def getLogger(*args):
            return logging()

        @staticmethod
        def basicConfig(*args):
            pass

        def info(self, *args):
            print(*args)

        def excep(self, *args):
            print("ERR", *args)


log = logging.getLogger("uaioftpd")

month_alias = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]


class AccessDenied(Exception):
    def __repr__(self):
        return "AccessDenied"


class wait_connection(object):
    """
    limit number of incoming connections
    """

    def __init__(self, session, accurrancy=0.1):
        self.ftpd = session.ftpd
        self.accurrancy = accurrancy
        # todo add timeout handling

    async def __aenter__(self):
        while True:
            if self.ftpd.max_clients > 0:
                self.ftpd.max_clients -= 1
                log.info("allocated client connection. free:=", self.ftpd.max_clients)
                return self
            await asyncio.sleep(self.accurrancy)

    async def __aexit__(self, ex_type, ex_value, traceback):
        self.ftpd.max_clients += 1
        log.info("released client connection. free:=", self.ftpd.max_clients)


class Session(object):
    def __init__(self, ftpd):
        self.ftpd = ftpd
        self.session_ok = False
        self.user = None
        self.mode = "S"
        self.mode_type = "I"
        self.pasv = False
        self.cwd = "/"
        self.rename_from = None

    def check_session(self):
        if self.session_ok is False:
            raise AccessDenied()

    def requires_login(self):
        return self.ftpd.user_credits != None

    def check_user(self, user):
        if self.requires_login() is False:
            return True
        return user in self.ftpd.user_credits

    def check_passwd(self, passwd):
        if self.requires_login() is False:
            return True
        return self.ftpd.user_credits[self.user] == passwd

    def split(self, s, sep=None, maxsplit=-1):
        if maxsplit < 0:
            return s.split(sep)
        rc = []
        pos = s.find(sep)
        if pos < 0:
            return [s]
        if maxsplit > 1:
            raise NotImplementedError()
        return [s[:pos], s[pos + 1 :]]

    def strip_quotes(self, s):
        if s is None:
            return s
        # todo proper handling of quotes
        if s.startswith("\"'"):
            s = s[1:]
        if s.endswith("\"'"):
            s = s[:-1]
        return s

    def build_path(self, argument):
        if argument is None:
            return self.cwd
        if argument.startswith("/"):
            return argument
        # filter empty unnecessary empty path spec with //
        pathspec = list(filter(lambda x: len(x) > 0, argument.split("/")))
        cwd = str(self.cwd)
        while len(pathspec) > 0:
            cur = pathspec.pop(0)
            if cur == ".":
                continue
            elif cur == "..":
                pos = cwd.rfind("/")
                if pos < 0:
                    # already at root level
                    cwd = "/"
                    continue
                cwd = cwd[:pos]
                if cwd == "":
                    # already at root level
                    cwd = "/"
            else:
                sep = "" if cwd.endswith("/") else "/"
                cwd += sep + cur
        return cwd

    async def serve(self, reader, writer):
        addr = writer.get_extra_info("peername")
        log.info("client from {}".format(addr))
        await writer.awrite("220 Welcome to WY micro FTP server\r\n")
        while self.ftpd.stopped is False:
            try:
                data = await reader.readline()
            except OSError as ex:
                log.excep(ex)
                break
            if data is None or len(data) == 0:
                log.info("no data, break")
                break
            else:
                log.info("recv = %s" % data)
                data = data.decode("utf-8").strip()
                # split into cmd and rest of line
                # to support also folder names with blanks
                # todo micropython specific, maxsplit not supported for split()
                split_data = self.split(data, " ", maxsplit=1)
                cmd = "cmd_" + split_data[0]  # .strip("\r\n")
                argument = split_data[1] if len(split_data) > 1 else None
                log.info("cmd is %s, argument is %s" % (cmd, argument))
                if hasattr(self, cmd):
                    func = getattr(self, cmd)
                    try:
                        keep_open = True
                        result = await func(writer, argument)
                        if type(result) == tuple:
                            result, keep_open = result
                        log.info("result = %d" % result)
                        if not result:
                            break
                        if keep_open is False:
                            break
                    except OSError as ex:
                        log.excep(ex)
                        break
                    except AccessDenied as ex:
                        log.excep(ex)
                        await writer.awrite("530 Not logged in.\r\n")
                        break
                else:
                    await writer.awrite("520 not implement.\r\n")
        await writer.wait_closed()

    async def cmd_USER(self, stream, argument):
        self.session_ok = False
        self.user = None
        argument = argument.lower()
        if self.check_user(argument) is False:
            await stream.awrite("550 Access denied.\r\n")
        else:
            self.user = argument
            await stream.awrite("331 OK.\r\n")
        return True

    async def cmd_PASS(self, stream, argument):
        self.session_ok = False
        if self.check_passwd(argument) is False:
            await stream.awrite("550 Access denied.\r\n")
        else:
            self.session_ok = True
            await stream.awrite("230 OK.\r\n")
        return True

    async def cmd_PWD(self, stream, argument):
        self.check_session()

        try:
            # cwd = os.getcwd()
            cwd = self.cwd
            await stream.awrite('250 "{}".\r\n'.format(cwd))
        except OSError as e:
            await stream.awrite("550 {}.\r\n".format(e))
        return True

    async def cmd_SYST(self, stream, argument):
        await stream.awrite("215 " + sys.platform + " " + sys.version + "\r\n")
        return True

    async def cmd_CWD(self, stream, argument):
        self.check_session()

        log.info("CWD argument is %s" % argument)
        try:
            argument = self.strip_quotes(argument)
            # os.chdir(argument)
            path = self.build_path(argument)
            os.stat(path)
            self.cwd = path

            log.info("new path", self.cwd)

            await stream.awrite("250 OK.\r\n")
        except OSError as e:
            await stream.awrite("550 {}.\r\n".format(e))
        return True

    async def cmd_QUIT(self, stream, argument):
        await stream.awrite("221 Bye!.\r\n")
        return False

    async def cmd_DELE(self, stream, argument):
        self.check_session()

        try:
            argument = self.strip_quotes(argument)
            path = self.build_path(argument)
            os.remove(path)
            await stream.awrite("257 OK.\r\n")
        except OSError as e:
            await stream.awrite("550 {}.\r\n".format(e))
        return True

    async def cmd_MKD(self, stream, argument):
        self.check_session()

        try:
            argument = self.strip_quotes(argument)
            path = self.build_path(argument)
            os.mkdir(path)
            await stream.awrite("257 OK.\r\n")
        except OSError as e:
            await stream.awrite("550 {}.\r\n".format(e))
        return True

    async def cmd_RMD(self, stream, argument):
        self.check_session()
        try:
            argument = self.strip_quotes(argument)
            path = self.build_path(argument)
            os.rmdir(path)
            await stream.awrite("257 OK.\r\n")
        except OSError as e:
            await stream.awrite("550 {}.\r\n".format(e))
        return True

    async def cmd_CDUP(self, stream, argument):
        self.check_session()

        argument = ".."  # if not argument else ".."
        # argument = self.strip_quotes(argument)
        log.info("CDUP argument is %s" % argument)
        try:
            path = self.build_path(argument)
            os.stat(path)
            self.cwd = path
            # os.chdir(path)
            await stream.awrite("250 OK.\r\n")
        except Exception as e:
            await stream.awrite("550 error {}.\r\n".format(e))
        return True

    async def cmd_TYPE(self, stream, argument):
        if argument == "I":
            self.mode_type = "I"
            await stream.awrite("200 Binary Representation.\r\n")
        else:
            await stream.awrite("504 Command not implemented for that parameter.\r\n")
        return True

    async def cmd_MODE(self, stream, argument):
        if argument == "S":
            self.mode = "S"
            await stream.awrite("200 Stream mode.\r\n")
        else:
            await stream.awrite("504 Command not implemented for that parameter.\r\n")
        return True

    async def cmd_RNFR(self, stream, argument):
        self.rename_from = None
        argument = self.strip_quotes(argument)
        if len(argument) > 0:
            self.rename_from = argument
            await stream.awrite("200 Rename file OK.\r\n")
        else:
            await stream.awrite("550 Parameter missing.\r\n")
        return True

    async def cmd_RNTO(self, stream, argument):
        argument = self.strip_quotes(argument)
        if len(argument) > 0 and self.rename_from:
            rename_from = self.build_path(self.rename_from)
            rename_to = self.build_path(argument)
            try:
                os.rename(rename_from, rename_to)
                await stream.awrite("200 Rename file OK.\r\n")
            except Exception as ex:
                await stream.awrite("550 error {}.\r\n".format(ex))
            self.rename_from = None

        else:
            await stream.awrite("550 Parameter missing.\r\n")
        return True

    async def cmd_PORT(self, stream, argument):
        self.check_session()

        argument = argument.split(",")
        self.data_ip = ".".join(argument[:4])
        self.data_port = (int(argument[4]) << 8) + int(argument[5])
        self.data_addr = (self.data_ip, self.data_port)
        log.info("got the port {}".format(self.data_addr))
        await stream.awrite("220 Got the port.\r\n")
        return True

    async def cmd_PASV(self, stream, argument):
        await stream.awrite("550 not support now.\r\n")
        return True

    async def cmd_LIST(self, stream, argument):
        self.check_session()

        argument = self.strip_quotes(argument)
        path = self.build_path(argument)

        try:
            os.stat(path)
        except:
            await stream.awrite("550 Directory not found.\r\n")
            return False, True

        async with wait_connection(self):
            await stream.awrite("150 Here comes the directory listing.\r\n")
            # path = os.getcwd() if argument is None else argument  # .decode("UTF-8")
            if self.pasv is False:
                log.info("LIST connecting to %s %d" % (self.data_ip, self.data_port))
                reader, writer = await asyncio.open_connection(
                    self.data_ip, self.data_port
                )
                log.info("connection established")

                items = os.listdir(path)
                if path == "/":
                    path = ""

                for i in items:
                    file_stat = os.stat(path + "/" + i)
                    file_date = file_stat[-2]
                    file_size = file_stat[-4]

                    file_type = "d" if file_stat[0] == 0x4000 else "-"

                    format_date = time.localtime(file_date)

                    # todo check against RFC
                    # if file year is different from current year
                    # then listing should/ can contain the year instead of hh:mm
                    await writer.awrite(
                        "%srwxrwxrwx user group %10d %s %2d %d:%d %s\r\n"
                        % (
                            file_type,
                            file_size,
                            month_alias[format_date[1] - 1],
                            format_date[2],
                            format_date[3],
                            format_date[4],
                            i,
                        )
                    )
                await writer.wait_closed()
            await stream.awrite("226 Directory send OK.\r\n")
            return True

    async def cmd_RETR(self, stream, argument):
        self.check_session()

        max_chuck_size = self.ftpd.max_chuck_size

        async with wait_connection(self):
            await stream.awrite("150 Opening data connection.\r\n")
            if self.pasv is False:
                log.info("RETR connecting to %s %d" % (self.data_ip, self.data_port))
                reader, writer = await asyncio.open_connection(
                    self.data_ip, self.data_port
                )
                log.info("connection established")
                path = self.build_path(argument)
                remaining_size = os.stat(path)[-4]
                try:
                    log.info("open for transmission", self.mode_type, path)
                    with open(path, "rb") if self.mode_type == "I" else open(
                        path, "r"
                    ) as f:
                        while True:
                            buf = f.read(max_chuck_size)
                            blen = len(buf)
                            if blen == 0:
                                break
                            await writer.awrite(buf)
                    await stream.awrite("226 Transfer complete.\r\n")
                except OSError as e:
                    log.excep("transmittion error", e)
                    if e.args[0] == uerrno.ENOENT:
                        await stream.awrite("550 No such file.\r\n")
                    else:
                        await stream.awrite("550 Open file error.\r\n")
                except Exception as ex:
                    log.excep("File i/o error", ex)
                    await stream.awrite("550 File i/o error {}.\r\n".format(ex))
                finally:
                    await writer.wait_closed()
            # del buf
            return True

    async def cmd_STOR(self, stream, argument):
        self.check_session()

        max_chuck_size = self.ftpd.max_chuck_size

        async with wait_connection(self):
            await stream.awrite("150 Opening data connection.\r\n")
            if self.pasv is False:
                log.info("STOR connecting to %s %d" % (self.data_ip, self.data_port))
                reader, writer = await asyncio.open_connection(
                    self.data_ip, self.data_port
                )
                log.info("connection established")
                try:
                    path = self.build_path(argument)
                    with open(path, "wb") if self.mode_type == "I" else open(
                        path, "w"
                    ) as f:
                        f.seek(0)
                        while True:
                            try:
                                data = await reader.read(max_chuck_size)
                                if data is None or len(data) == 0:
                                    break
                                bywr = f.write(data)
                                if bywr != len(data):
                                    raise OSError("check free space on disc.")
                            except Exception as e:
                                log.info("exception .. {}".format(e))
                                break
                    await stream.awrite("226 Transfer complete.\r\n")
                except OSError as e:
                    await stream.awrite("550 File i/o error. {}\r\n".format(e))
                finally:
                    await writer.wait_closed()
            return True, False


class uaioftpd:
    def __init__(
        self,
        loop=None,
        my_ip="192.168.0.1",
        max_clients=3,
        user_credits=None,
        data_port=20,
    ):
        self.loop = loop
        self.data_port = data_port
        self.ip = my_ip
        self.max_chuck_size = 512
        self.stopped = False
        self.max_clients = max_clients
        self._set_credits(user_credits)

    def _set_credits(self, user_credits):
        if type(user_credits) == dict or user_credits is None:
            self.user_credits = user_credits
            return
        self.user_credits = {}
        for u, p in user_credits:
            self.user_credits[u.lower()] = p

    async def server(self, reader, writer):
        session = Session(self)
        await session.serve(reader, writer)
