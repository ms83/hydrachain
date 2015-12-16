import os
import time
import signal
import syslog
import pytest
import random
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


def drive_test():
    def log(msg):
        """ Stdin is grabbed by CLIRunner. To read logs comment out below and read syslog.
        i.e. tail -F /var/log/syslog
        """
        #syslog.syslog(syslog.LOG_DEBUG, "[{} drive_test] {}".format(time.time(), msg))
        pass

    def wait_for_new_block(client, filter_id):
        while True:
            log('wait_for_new_block')
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

    # Set up filter to get notified when a new block arrives
    new_block_filter_id = client.call('eth_newBlockFilter')

    # Create a contract
    params = {'from': client.coinbase.encode('hex'), 'to': '', 'data': contract_code}
    client.call('eth_sendTransaction', params)

    # Wait for new block
    recent_block_hash = wait_for_new_block(client, new_block_filter_id)

    recent_block = client.call('eth_getBlockByHash', recent_block_hash, True)
    log('recent_block {}'.format(recent_block))

    assert recent_block['transactions']
    tx = recent_block['transactions'][0]
    assert tx['to'] == '0x'
    assert tx['input'].startswith('0x')
    assert len(tx['input']) > len('0x')

    # Get transaction receipt to have the address of contract
    receipt = client.call('eth_getTransactionReceipt', tx['hash'])
    log('receipt {}'.format(receipt))

    assert receipt['transactionHash'] == tx['hash']
    assert receipt['blockHash'] == tx['blockHash']
    assert receipt['blockHash'] == recent_block['hash']

    # Get contract address from receipt
    contract_address = receipt['contractAddress']
    code = client.call('eth_getCode', contract_address)
    log("code {}".format(code))

    assert code.startswith('0x')
    assert len(code) > len('0x')

    # Perform some action on contract (set value to 50)
    rand_value = random.randint(50, 1000)
    contract = client.new_abi_contract(contract_interface, contract_address)
    contract.set(rand_value)

    # Wait for new block
    recent_block_hash = wait_for_new_block(client, new_block_filter_id)
    recent_block = client.call('eth_getBlockByHash', recent_block_hash, True)

    # Check that value was correctly set on contract
    res = contract.get()
    log("contract.get() {}".format(res))
    assert res == rand_value

    # Stop me and CliRunner
    os.kill(os.getpid(), signal.SIGINT)


@pytest.mark.timeout(10)
def test():
    # Start thread that will communicate to the app ran by CliRunner
    d = Thread(target=drive_test)
    d.setDaemon(True)
    d.start()

    runner = CliRunner()
    runner.invoke(app.pyethapp_app.app, ['-d', 'datadir', 'runmultiple'])
    """
    ['-d', 'datadir', '--log-file', '/tmp/hydra.log',
     '-l', 'eth:debug,jsonrpc:debug', 'runmultiple'])
    """


if __name__ == '__main__':
    test()
