import time
import uasyncio as asyncio
from uaioftp import uaioftpd
import network

wlan = network.WLAN(network.STA_IF)
wlan.active(True)

ssid, passwd = ("your-ssid", "yourpass-wd")

wlan.connect(ssid, passwd)

while wlan.isconnected() is False:
    time.sleep(1)
    print("waiting for wlan")

ip_addr = wlan.ifconfig()[0]
print("wlan", ip_addr)

# https://datatracker.ietf.org/doc/html/rfc959
# see section 5.2. page 43
# default data port is minus 1 from cmd_port
cmd_port = 21
data_port = cmd_port - 1

user_credits = [("cwyark", "topsecret"), ("karl", "hidden")]
# user_credits = {"cwyark": "topsecret", "karl": "hidden"}
# no anonymous login when set to None
user_credits = None

loop = asyncio.get_event_loop()

ftpd = uaioftpd(
    loop=loop, my_ip=ip_addr, user_credits=user_credits, data_port=data_port
)

server = asyncio.start_server(ftpd.server, "0.0.0.0", cmd_port)
server_t = loop.create_task(server)


async def main():
    while True:
        await asyncio.sleep(5)


loop.create_task(main())
loop.run_forever()
