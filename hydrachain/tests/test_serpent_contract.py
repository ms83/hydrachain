from ethereum import tester
import serpent
import logging
logging.NOTSET = logging.INFO
tester.disable_logging()


def test_send_contract():
    serpent_code = '''
def main(a,b):
    return(a ^ b)
'''
    s = tester.state()
    assert len(s.blocks) == 1
    head = s.blocks[0]
    evm_code = serpent.compile(serpent_code)
    s._send(tester.k0, b'', 0, evmdata=evm_code)
    creates = head.get_transaction(0).creates
    s.mine()

    assert len(s.blocks) == 2
    head = s.blocks[-1]
    code = head.account_to_dict(creates)['code']
    assert len(code) > 2
    assert code != '0x'
