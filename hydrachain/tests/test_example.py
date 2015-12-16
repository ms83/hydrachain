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
    def run(self):
        # Stdin is grabbed by CLIRunner so logs are stored internally
        self.test_output = ['test driver started']
        self.test_successful = False

        def wait_for_new_block(client, filter_id):
            while True:
                self.test_output.append('wait_for_new_block')
                block_hashes = client.call('eth_getFilterChanges', filter_id)
                time.sleep(0.5)
                if block_hashes:
                    assert len(block_hashes) == 1
                    return block_hashes[0]

        # Poll app until RPC interface is ready
        while True:
            try:
                client = JSONRPCClient()
                client.call('web3_clientVersion')
                break
            except ConnectionError, e:
                time.sleep(0.5)

        try:
            # Set up filter to get notified when a new block arrives
            new_block_filter_id = client.call('eth_newBlockFilter')
            self.test_output.append('eth_newBlockFilter OK')

            # Create a contract
            params = {'from': client.coinbase.encode('hex'), 'to': '', 'data': contract_code}
            client.call('eth_sendTransaction', params)
            self.test_output.append('eth_sendTransaction OK')

            # Wait for new block
            recent_block_hash = wait_for_new_block(client, new_block_filter_id)

            recent_block = client.call('eth_getBlockByHash', recent_block_hash, True)
            self.test_output.append('eth_getBlockByHash OK {}'.format(recent_block))

            assert recent_block['transactions']
            tx = recent_block['transactions'][0]
            assert tx['to'] == '0x'
            assert tx['input'].startswith('0x')
            assert len(tx['input']) > len('0x')

            # Get transaction receipt to have the address of contract
            receipt = client.call('eth_getTransactionReceipt', tx['hash'])
            self.test_output.append('eth_getTransactionReceipt OK {}'.format(receipt))

            assert receipt['transactionHash'] == tx['hash']
            assert receipt['blockHash'] == tx['blockHash']
            assert receipt['blockHash'] == recent_block['hash']

            # Get contract address from receipt
            contract_address = receipt['contractAddress']
            code = client.call('eth_getCode', contract_address)
            self.test_output.append('eth_getCode OK {}'.format(code))

            assert code.startswith('0x')
            assert len(code) > len('0x')

            # Perform some action on contract (set value to 50)
            rand_value = random.randint(50, 1000)
            contract = client.new_abi_contract(contract_interface, contract_address)
            contract.set(rand_value)
            self.test_output.append('contract.set() OK')

            # Wait for new block
            recent_block_hash = wait_for_new_block(client, new_block_filter_id)
            recent_block = client.call('eth_getBlockByHash', recent_block_hash, True)

            # Check that value was correctly set on contract
            res = contract.get()
            self.test_output.append('contract.get() OK {}'.format(res))
            assert res == rand_value

            self.test_successful = True
        except Exception, e:
            self.test_output.append(unicode(e))


def test_example():
    # Start thread that will communicate to the app ran by CliRunner
    t = TestDriverThread()
    t.setDaemon(True)
    t.start()

    # Stop app after 10 seconds which is neccessary to complete the test
    def mock_serve_until_stopped(apps):
        gevent.sleep(10)

    app.serve_until_stopped = mock_serve_until_stopped
    runner = CliRunner()
    runner.invoke(app.pyethapp_app.app, ['-d', 'datadir', 'runmultiple'])

    assert t.test_successful, '\n'.join(t.test_output)
    """
    ['-d', 'datadir', '--log-file', '/tmp/hydra.log',
     '-l', 'eth:debug,jsonrpc:debug', 'runmultiple'])
    """


if __name__ == '__main__':
    test_example()
