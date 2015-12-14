import os
import time
import signal
import syslog
import pytest
import traceback
from threading import Thread
from click.testing import CliRunner
from hydrachain import app
from pyethapp.rpc_client import JSONRPCClient
from requests.exceptions import ConnectionError


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


def drive_test():
    def log(msg):
        syslog.syslog(syslog.LOG_DEBUG, "[{} drive_test] {}".format(time.time(), msg))
        pass

    def wait_for_new_block(client):
        while True:
            log('busy loop')
            block_hashes = client.call('eth_getFilterChanges', new_block_filter_id)
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

    # Set up filter to get notified when a new block arrives
    new_block_filter_id = client.call('eth_newBlockFilter')

    # Create a contract
    client.eth_sendTransaction(sender=client.coinbase, to='', data=contract_code)

    # Wait for new block
    recent_block_hash = wait_for_new_block(client)

    recent_block = client.call('eth_getBlockByHash', recent_block_hash, True)
    assert recent_block['transactions']
    # FIXME - more asserts

    # Perform some action on contract (set value to 50)
    contract = client.new_abi_contract(contract_interface, '')
    contract.set(50)

    # Wait for new block
    recent_block_hash = wait_for_new_block(client)
    recent_block = client.call('eth_getBlockByHash', recent_block_hash, True)

    # FIXME - assert that value was set
    contract.get()

    # Stop me and CliRunner
    os.kill(os.getpid(), signal.SIGINT)


@pytest.mark.timeout(10)
def test():
    # Start thread that will communicate to app ran by CliRunner
    d = Thread(target=drive_test)
    d.setDaemon(True)
    d.start()

    runner = CliRunner()
    runner.invoke(app.pyethapp_app.app,
                  ['-d', 'datadir', '--log-file', '/tmp/hydra.log', 'runmultiple'])
                                                   # FIXME


if __name__ == '__main__':
    test()
