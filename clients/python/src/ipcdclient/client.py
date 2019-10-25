import asyncio
import certifi
import json
import urllib3
import websockets
import logging
import threading

from .command import from_payload

__all__ = ['IpcdClient']


def _validate_hostname(hostname):
  if not hostname:
    raise ValueError("hostname must be set")


class IpcdClient(object):
  """
  A simple IP Connected Device (IPCD) Client
  https://github.com/arcus-smart-home/arcusipcd
  """
  IPCD_VERSION = '1.0'

  class Device(object):
    """
    Represents a Device.
    """

    def __init__(self, vendor, model, sn, ipcd_version=None):
      self.vendor = vendor
      self.model = model
      self.sn = sn
      if not ipcd_version:
        self.ipcd_version = IpcdClient.IPCD_VERSION
      self._client = None

    def to_obj(self):
      data = {
        'ipcdver': self.ipcd_version,
        'vendor':  self.vendor,
        'model':   self.model,
        'sn':      self.sn
      }

      return data

    def _set_client(self, client):
      """
      Used to support Device methods.
      :param client:
      :return:
      """
      self._client = client

    def get_client(self):
      """
      Callers should not attempt to use the client directly. In the future this is likely to be stubbed
      with a "NoopClient" for cases where a client is not available.
      :return:
      """
      return self._client

    async def on_message(self, message):
      """

      :param message:
      :return:
      """
      from_payload(message).apply(self)

  def __init__(self, hostname):
    _validate_hostname(hostname)
    self.hostname = hostname
    self.ipcd_version = self.IPCD_VERSION
    self.pool = urllib3.PoolManager(cert_reqs='CERT_REQUIRED', ca_certs=certifi.where())
    self.devices = []
    self.queue = asyncio.Queue()
    self._setup_logger()

  def _setup_logger(self):
    self.logger = logging.getLogger(__name__)
    self.logger.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    self.logger.addHandler(ch)

  def get_report_url(self, device):
    """
      Gets the report url. The IPCD spec says this should be
      /ipcd/<ipcdver>/report/<vendor_key>/<model_key>/<sn>

      :param device:
      :return:
      """
    return self.hostname + '/ipcd/{}/report/{}/{}/{}'.format(self.ipcd_version, device.vendor, device.model, device.sn)

  def report(self, device, report):
    """
    Report via on-demand url (currently not supported in Arcus Platform)
    :param device:
    :param report:
    :return:
    """
    url = self.get_report_url(device)
    data = {
      'device': {
        'ipcdver': self.ipcd_version,
        'vendor': device.vendor,
        'model': device.model,
        'sn': device.sn
      },
      'report': report
    }

    request = self.pool.request('POST', url, body=json.dumps(data), headers={
      'Content-Type': 'application/json', 'User-Agent': 'Arcus IPCD Client 1.0'
    })

    return request

  def add_device(self, device):
    device._set_client(self)
    self.devices.append(device)

  def connect(self):
    """
    Connect to the server via websockets
    :return:
    """

    async def connect_loop():
      async with websockets.connect(self.hostname + '/ipcd/1.0') as websocket:
        loop = asyncio.get_event_loop()

        # First, add all the pre-registered devices.
        for device in self.devices:
          data = {
            'device': {
              'ipcdver': self.ipcd_version,
              'vendor': device.vendor,
              'model': device.model,
              'sn': device.sn
            },
            'events': ['onBoot', 'onConnect']
          }

          await websocket.send(json.dumps(data))

        async def reader(websocket):
          while True:
            msg = await websocket.recv()
            loop.create_task(self.devices[0].on_message(json.loads(msg)))

        async def writer(websocket):
          while True:
            msg = await self.queue.get()
            await websocket.send(msg)

        loop.create_task(reader(websocket))
        loop.create_task(writer(websocket))

        await websocket.wait_closed()

    def loop_in_thread(loop):
      asyncio.set_event_loop(loop)
      loop.run_until_complete(connect_loop())

    loop = asyncio.get_event_loop()
    t = threading.Thread(target=loop_in_thread, args=(loop,))
    t.start()

  def disconnect(self):
    pass  # TODO

  def send(self, device, message):
    """
    Wrapper. Need to rename!
    :param device:
    :param message:
    :return:
    """
    self.on_value_change(device, message)

  def on_value_change(self, device, message):
    """
    Send a device report over IPCD
    :param device:
    :param message:
    :return:
    """
    data = {
      'device': {
        'ipcdver': self.ipcd_version,
        'vendor': device.vendor,
        'model': device.model,
        'sn': device.sn,
      },
      'events': ['onValueChanges'],
      'valueChanges': message
    }

    payload = json.dumps(data)
    self.logger.info("putting %s on the queue", payload)
    self.queue.put_nowait(payload)

  def report(self, device, message):
    """
    Send a device report over IPCD
    :param device:
    :param message:
    :return:
    """
    data = {
      'device': {
        'ipcdver': self.ipcd_version,
        'vendor': device.vendor,
        'model': device.model,
        'sn': device.sn,
      },
      'report': message
    }

    payload = json.dumps(data)
    self.logger.info("report: putting %s on the queue", payload)
    self.queue.put_nowait(payload)


def main():
  """
  TODO: write a simple app to test from command line.
  :return:
  """


if __name__ == "__main__":
  main()
