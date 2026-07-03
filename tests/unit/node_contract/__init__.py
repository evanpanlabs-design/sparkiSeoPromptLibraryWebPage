# Node Contract Tests
#
# Each file tests that a node's INPUT/OUTPUT contract (docs/03_InterfaceContract.md §5)
# is respected — i.e., the node reads only what it declares and writes only what it promises.
#
# Run all:     pytest tests/unit/node_contract/ -v
# Run one:     pytest tests/unit/node_contract/test_crawler_contract.py -v

from tests.unit.node_contract.conftest import *  # noqa: F401, F403