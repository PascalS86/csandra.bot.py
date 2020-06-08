import asyncio
import json
from enum import Enum

class WorkState(Enum):
    RETURN_TO_BASE = 4
    CLEANING = 1
    PENDING = 2
    UNKNONW3 = 3
    NEAR_BASE = 5
    CHARGING = 6
    POWER_OFF = 7
    OTHER_POWER_OFF = 0

class ProscenicBot():

    def __init__(self, ip, auth, loop = None, config = {}):
        self.ip = ip
        self.battery = None
        self.fan_speed = 2
        self.work_state = WorkState.CHARGING
        self.subscribers = []
        self.loop = loop
        self.auth = auth
        self.device_id = auth['deviceId']
        self.sleep_duration_on_exit = config['sleep_duration_on_exit'] if 'sleep_duration_on_exit' in config  else 60
        
    async def state_change(self):
        try:
            await self._start_listen()
        except:
            print('error while listening bot state change')
        
    def subcribe(self, subscriber):
        self.subscribers.append(subscriber)
        
    async def clean(self):
        await self._transit_cmd(b'{"transitCmd":"100"}')
    
    async def stop(self):
        await self._transit_cmd(b'{"transitCmd":"102"}')

    async def return_to_base(self):
        await self._transit_cmd(b'{"transitCmd":"104"}')

    async def check_robot_status(self):
        try:
            await self._transit_cmd(b'{"transitCmd":"131"}')
            if self.work_state == WorkState.POWER_OFF or self.work_state == WorkState.OTHER_POWER_OFF:
                self.work_state = WorkState.PENDING
        except ProscenicBotUnavailable:
            self.work_state = WorkState.POWER_OFF 
            self._call_subscribers()

    async def _transit_cmd(self, command: bytes, input_writer = None):
        try:
            if not input_writer:
                (_, writer) = await asyncio.open_connection(self.ip, 8888, loop = self.loop)
            else:
                writer = input_writer
            
            header = b'\xd2\x00\x00\x00\xfa\x00\xc8\x00\x00\x00\xeb\x27\xea\x27\x00\x00\x00\x00\x00\x00'
            body = b'{"cmd":0,"control":{"authCode":"' \
                + str.encode(self.auth['authCode']) \
                + b'","deviceIp":"' \
                + str.encode(self.ip) \
                + b'","devicePort":"8888","targetId":"' \
                + str.encode(self.auth['deviceId']) \
                + b'","targetType":"3"},"seq":0,"value":' \
                + command  \
                + b',"version":"1.5.11"}'
            print('send command {}'.format(str(body)))
            writer.write(header + body)
            await writer.drain()

            if not input_writer:
                writer.close()
                await writer.wait_closed()
        except OSError:
            raise ProscenicBotUnavailable('can not connect to the robot.')

    async def _ping_bot(self, writer):
        body = b'\x14\x00\x00\x00\x00\x01\xc8\x00\x00\x00\x01\x00\x22\x27\x00\x00\x00\x00\x00\x00'
        writer.write(body)
        await writer.drain()
        
    async def _login(self, writer):
        header = b'\xfb\x00\x00\x00\x10\x00\xc8\x00\x00\x00\x29\x27\x2a\x27\x00\x00\x00\x00\x00\x00'
        body = b'{"cmd":0,"control":{"targetId":""},"seq":0,"value":{"appKey":"67ce4fabe562405d9492cad9097e09bf","deviceId":"' \
            + str.encode(self.auth['deviceId']) \
            + b'","deviceType":"3","token":"' \
            + str.encode(self.auth['token']) \
            + b'","userId":"' \
            + str.encode(self.auth['userId']) \
            + b'"}}'
        writer.write(header + body)
        await writer.drain()

    async def _wait_for_next_workState(self, reader):
        disconnected = False
        while not disconnected:
            data = await reader.read(1000)
            if data != b'':
                print(str(data))
                data = self._get_json_from_data(data)
                if data and'msg' in data and data['msg'] == 'exit succeed':
                    print('receive exit succeed - disconnected')
                    disconnected = True
                elif data and 'value' in data:
                    values = data['value']
                    if 'workState' in values  and values['workState'] != '':
                        try:
                            self.work_state = WorkState(int(values['workState']))
                        except:
                            print('error setting work state {}'.format(str(values['workState'])))
                    if self.work_state != WorkState.POWER_OFF:
                        if 'battery' in values and values['battery'] != '':
                            self.battery = int(values['battery'])
                        if 'fan' in values  and values['fan'] != '':
                            self.fan_speed = int(values['fan'])
                   
                    self._call_subscribers()
            else:
                print('receive empty message - disconnected')
                disconnected = True

        return disconnected

    async def _start_listen(self):
        await self.check_robot_status()
        while True:
            try:
                print('sign in to proscenic server')
                (reader, writer) = await asyncio.open_connection('47.91.67.181', 20008, loop = self.loop)
                await self._login(writer)
                disconnected = False
                while not disconnected:
                    try:
                        disconnected = await asyncio.wait_for(self._wait_for_next_workState(reader), timeout=60.0)
                    except asyncio.TimeoutError:
                        await self._ping_bot(writer)
                        await self.check_robot_status()

                print('sleep {} second before reconnecting'.format(self.sleep_duration_on_exit))
                await asyncio.sleep(self.sleep_duration_on_exit)
            except OSError:
                print('error on refresh loop')

    def _call_subscribers(self):
        for subscriber in self.subscribers:
            subscriber(self)

    def _get_json_from_data(self, response):
        first_index = response.find(b'{')
        last_index = response.rfind(b'}')
        if first_index >= 0 and last_index >= 0:
            try:
                return json.loads(response[first_index:(last_index + 1)])
            except:
                print('error loading json {}'.format(response[first_index:(last_index + 1)]))
                return None

        return None


class ProscenicBotUnavailable(Exception):
    pass