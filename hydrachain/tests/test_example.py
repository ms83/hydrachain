import os
import time
import signal
import syslog
import pytest
import random
import gevent
import traceback
from threading import Thread
from click.testing import CliRunner
from hydrachain import app
from pyethapp.rpc_client import JSONRPCClient
from requests.exceptions import ConnectionError
from ethereum.processblock import mk_contract_address


solidity_code = """
contract SimpleStorage {
    uint storedData;
    function set(uint x) {
        storedData = x;
    }
    function get() constant returns (uint retVal) {
        return storedData;
    }
}
"""

# Compiled with https://chriseth.github.io/browser-solidity/
contract_interface = '[{"constant":false,"inputs":[{"name":"x","type":"uint256"}],"name":"set","outputs":[],"type":"function"},{"constant":true,"inputs":[],"name":"get","outputs":[{"name":"retVal","type":"uint256"}],"type":"function"}]'

contract_code = "606060405260978060106000396000f360606040526000357c01000000000000000000000000000000000000000000000000000000009004806360fe47b11460415780636d4ce63c14605757603f565b005b605560048080359060200190919050506078565b005b606260048050506086565b6040518082815260200191505060405180910390f35b806000600050819055505b50565b600060006000505490506094565b9056"


class TestDriverThread(Thread):

    def log(self, msg):
        msg = '{} {}'.format(time.time(), msg)
        self.test_output.append(msg)
        #syslog.syslog(syslog.LOG_DEBUG, msg)

    def wait_for_new_block(self, timeout=0):
        start_ts = time.time()
        while True:
            self.log('wait_for_new_block')
            block_hashes = self.client.call('eth_getFilterChanges', self.new_block_filter_id)
            if block_hashes:
                return block_hashes[0]
            if timeout and time.time() - start_ts > timeout:
                return None
            time.sleep(0.5)

    def connect_client(self):
        while True:
            try:
                self.client = JSONRPCClient()
                self.client.call('web3_clientVersion')
                break
            except ConnectionError, e:
                time.sleep(0.5)

    def run(self):
        # Stdin is grabbed by CLIRunner so logs are stored internally
        self.test_output = []
        self.test_successful = False
        self.log('test started')

        try:
            self.connect_client()
            self.log('client connected')

            # Set up filter to get notified when a new block arrives
            self.new_block_filter_id = self.client.call('eth_newBlockFilter')
            self.log('eth_newBlockFilter OK')

            # Read initial blocks created by HydraChain on startup
            while self.wait_for_new_block(timeout=3):
                pass

            # Create a contract
            params = {'from': self.client.coinbase.encode('hex'),
                      'to': '',
                      'data': contract_code,
                      'gasPrice': '0x{}'.format(self.gasprice)}
            self.client.call('eth_sendTransaction', params)
            self.log('eth_sendTransaction OK')

            # Wait for new block
            recent_block_hash = self.wait_for_new_block()
            self.log('recent_block_hash {}'.format(recent_block_hash))

            recent_block = self.client.call('eth_getBlockByHash', recent_block_hash, True)
            self.log('eth_getBlockByHash OK {}'.format(recent_block))

            assert recent_block['transactions'], 'no transactions in block'
            tx = recent_block['transactions'][0]
            assert tx['to'] == '0x'
            assert tx['gasPrice'] == params['gasPrice']
            assert len(tx['input']) > len('0x')
            assert tx['input'].startswith('0x')

            # Get transaction receipt to have the address of contract
            receipt = self.client.call('eth_getTransactionReceipt', tx['hash'])
            self.log('eth_getTransactionReceipt OK {}'.format(receipt))

            assert receipt['transactionHash'] == tx['hash']
            assert receipt['blockHash'] == tx['blockHash']
            assert receipt['blockHash'] == recent_block['hash']

            # Get contract address from receipt
            contract_address = receipt['contractAddress']
            code = self.client.call('eth_getCode', contract_address)
            self.log('eth_getCode OK {}'.format(code))

            assert code.startswith('0x')
            assert len(code) > len('0x')

            # Perform some action on contract (set value to random number)
            rand_value = random.randint(64, 1024)
            contract = self.client.new_abi_contract(contract_interface, contract_address)
            contract.set(rand_value, gasprice=self.gasprice)
            self.log('contract.set({}) OK'.format(rand_value))

            # Wait for new block
            recent_block_hash = self.wait_for_new_block()
            recent_block = self.client.call('eth_getBlockByHash', recent_block_hash, True)

            # Check that value was correctly set on contract
            res = contract.get()
            self.log('contract.get() OK {}'.format(res))
            assert res == rand_value

            self.test_successful = True
        except Exception, e:
            self.log(unicode(e))


@pytest.mark.parametrize('gasprice', (0, 1))
def test_example(gasprice):
    # Start thread that will communicate to the app ran by CliRunner
    t = TestDriverThread()
    t.gasprice = gasprice
    t.setDaemon(True)
    t.start()

    # Stop app after 15 seconds which is neccessary to complete the test
    def mock_serve_until_stopped(apps):
        gevent.sleep(15)
        for app in apps:
            app.stop()

    app.serve_until_stopped = mock_serve_until_stopped
    runner = CliRunner()
    with runner.isolated_filesystem():
        datadir = 'datadir{}'.format(gasprice)
        runner.invoke(app.pyethapp_app.app, ['-d', datadir, 'runmultiple'])
        #runner.invoke(app.pyethapp_app.app, ['-d', datadir,
        #'-l', ':debug', '--log-file', '/tmp/hydra.log', 'runmultiple'])

    assert t.test_successful, '\n'.join(t.test_output)


if __name__ == '__main__':
    test_example(0)
    test_example(1)
