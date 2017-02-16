import logging
import uos as os
import usocket as _socket
import uasyncio as asyncio
import uerrno
import time

log = logging.getLogger("uaioftpd")

month_alias = ['Jan', 'Feb', 'Mar', 'Apr',
             'May', 'Jun', 'Jul', 'Aug',
             'Sep', 'Oct', 'Nov', 'Dec']


class uaioftpd:
    def __init__(self, loop=None, my_ip="192.168.0.1"):
        self.mode = "I"
        self.pasv = False
        self.loop = loop
        self.data_port = 12345
        self.ip = my_ip
        self.max_chuck_size = 512

    async def server(self, reader, writer):
        addr = writer.get_extra_info('peername')
    	log.info("client from {}".format(addr))
    	await writer.awrite("220 Welcome to WY micro FTP server\r\n")
        while True:
            data = await reader.readline()
            if not data:
                log.info("no data, break")
                await writer.aclose()
            else:
                log.info("recv = %s" % data)
                data = data.decode("utf-8")
                split_data = data.split(' ')
                cmd = split_data[0].strip('\r\n')
                argument = split_data[1].strip('\r\n') if len(split_data) > 1 else None
                log.info("cmd is %s, argument is %s" % (cmd, argument))
                if hasattr(self, cmd):
                    func = getattr(self, cmd)
                    result = await func(writer, argument)
                    log.info("result = %d" % result)
                    if not result:
                        await writer.aclose()
                        break
                else:
                    await writer.awrite("520 not implement.\r\n")


    async def USER(self, stream, argument):
        await stream.awrite("331 Okey.\r\n")
        return True

    async def PASS(self, stream, argument):
        await stream.awrite("230 Okey.\r\n")
        return True

    async def PWD(self, stream, argument):
        try:
            cwd = os.getcwd()
            await stream.awrite('250 "{}".\r\n'.format(cwd))
        except OSError as e:
            await stream.awrite('550 {}.\r\n'.format(e))
        return True

    async def SYST(self, stream, argument):
        await stream.awrite("215 ARM cortex M4 MCU.\r\n")
        return True

    async def CWD(self, stream, argument):
        log.info("CWD argument is %s" % argument)
        try:
            os.chdir(argument)
            await stream.awrite("250 Okey.\r\n")
        except OSError as e:
            await stream.awrite("550 {}.\r\n".format(e))
        return True

    async def QUIT(self, stream, argument):
        await stream.awrite("221 Bye!.\r\n")
        return False

    async def DELE(self, stream, argument):
        try:
            os.remove(argument)
            await stream.awrite("257 Okey.\r\n")
        except OSError as e:
            await stream.awrite("550 {}.\r\n".format(e))
        return True

    async def MKD(self, stream, argument):
        try:
            os.mkdir(argument)
            await stream.awrite("257 Okey.\r\n")
        except OSError as e:
            await stream.awrite("550 {}.\r\n".format(e))
        return True

    async def RMD(self, stream, argument):
        try:
            os.rmdir(argument)
            await stream.awrite("257 Okey.\r\n")
        except OSError as e:
            await stream.awrite("550 {}.\r\n".format(e))
        return True

    async def CDUP(self, stream, argument):
        argument = '..' if not argument else '..'
        log.info("CDUP argument is %s" % argument)
        try:
            os.chdir(argument)
            await stream.awrite("250 Okey.\r\n")
        except Exception as e:
            await stream.awrite("550 {}.\r\n".format(e))
        return True

    async def TYPE(self, stream, argument):
        if argument == "I":
            self.mode = "I"
            await stream.awrite("200 Binary mode.\r\n")
        else:
            await stream.awrite("502 {} not implement".format(argument))
        return True

    async def PORT(self, stream, argument):
        argument = argument.split(',')
        self.data_ip = '.'.join(argument[:4])
        self.data_port = (int(argument[4])<<8)+int(argument[5])
        self.data_addr = (self.data_ip, self.data_port)
        log.info("got the port {}".format(self.data_addr))
        await stream.awrite("220 Got the port.\r\n")
        return True

    async def PASV(self, stream, argument):
        await stream.awrite("550 not support now.\r\n")
        return True

    async def LIST(self, stream, argument):
        await stream.awrite("150 Here comes the directory listing.\r\n")
        path = os.getcwd() if argument is None else argument.decode("UTF-8")
        if self.pasv is False:
            log.info("LIST connecting to %s %d" % (self.data_ip, self.data_port))
            reader, writer = await asyncio.open_connection(self.data_ip, self.data_port)
            log.info("connection established")
            items = os.listdir(path)
            if path == '/':
                path = ''
            for i in items:
                file_stat = os.stat(path + "/" + i)
                file_date = file_stat[-2]
                file_size = file_stat[-4]
                file_type = 'd' if file_size == 0 else '-'
                format_date = time.localtime(file_date)
                await writer.awrite("%srwxrwxrwx user group %10d %s %2d %d:%d %s\r\n" %
                                    (file_type, file_size, month_alias[format_date[1] - 1],
                                     format_date[2], format_date[3], format_date[4], i))
            await writer.aclose()
        await stream.awrite("226 Directory send okey.\r\n")
        return True

    async def RETR(self, stream, argument):
        max_chuck_size = self.max_chuck_size
        buf = bytearray(max_chuck_size)
        await stream.awrite("150 Opening data connection\r\n")
        if self.pasv is False:
            log.info("RETR connecting to %s %d" % (self.data_ip, self.data_port))
            reader, writer = await asyncio.open_connection(self.data_ip, self.data_port)
            log.info("connection established")
            remaining_size = os.stat(argument)[-4]
            try:
                with open(argument, "rb") if self.mode == "I" else open(argument, "r") as f:
                    while remaining_size:
                        chuck_size = f.readinto(buf)
                        remaining_size -= chuck_size
                        mv = memoryview(buf)
                        ret = await writer.awrite(mv[:chuck_size])
                await stream.awrite("226 Transfer complete.\r\n")
            except OSError as e:
                if e.args[0] == uerrno.ENOENT:
                    await stream.awrite("550 No such file.\r\n")
                else:
                    await stream.awrite("550 Open file error.\r\n")
            finally:
                await writer.aclose()
        del buf
        return True

    async def STOR(self, stream, argument):
        max_chuck_size = self.max_chuck_size
        await stream.awrite("150 Opening data connection\r\n")
        if self.pasv is False:
            log.info("STOR connecting to %s %d" % (self.data_ip, self.data_port))
            reader, writer = await asyncio.open_connection(self.data_ip, self.data_port)
            log.info("connection established")
            try:
                with open(argument, "wb") if self.mode == "I" else open(argument, "w") as f:
                    f.seek(0)
                    while True:
                        try:
                            data = await reader.read(max_chuck_size)
                            f.write(data)
                            if not data:
                                break
                        except Exception as e:
                            log.info("exception .. {}".format(e))
                await stream.awrite("226 Transfer complete\r\n")
            except OSError as e:
                await stream.awrite("550 File i/o error.\r\n")
            finally:
                await writer.aclose()
        return True
