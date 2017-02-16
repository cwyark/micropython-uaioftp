# micropython-uaioftp
Lightweight ftp library for MicroPython.

## uaioftp server example

```
import uasyncio as asyncio
import logging
logging.basicConfig(level=logging.DEBUG)
#logging.basicConfig(level=logging.INFO)
loop = asyncio.get_event_loop()
from uaioftp import uaioftpd
ftpd = uaioftpd(loop=loop, my_ip=netif.ip()[0])
loop.call_soon(asyncio.start_server(ftpd.server, "0.0.0.0", 21))
try:
    loop.run_forever()
except:
    loop.close()
```
