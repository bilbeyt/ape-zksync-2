import enum
from typing import Iterator, List, Optional, Union

import rlp
from ape.api import ReceiptAPI, TransactionAPI
from ape.contracts import ContractEvent
from ape.exceptions import SignatureError
from ape.types import AddressType, ContractLog, GasLimit, MessageSignature
from ape_ethereum.transactions import Receipt, StaticFeeTransaction
from eth_typing import Hash32
from eth_utils import keccak
from ethpm_types.abi import EventABI
from hexbytes import HexBytes
from pydantic import Field

from ape_zksync.constants import CONTRACT_DEPLOYER_TYPE, ERC20_TYPE


class TransactionType(enum.Enum):
    LEGACY = 0x00
    ZKSYNC = 0x71


class LegacyTransaction(StaticFeeTransaction):
    """Legacy Ethereum Transaction"""

    type: int = Field(TransactionType.LEGACY.value, exclude=True, const=True)


class ZKSyncTransaction(TransactionAPI):
    """ZKSync Transaction"""

    gas_per_pubdata_byte_limit: int = Field(160_000, alias="ergsPerPubdataByteLimit")
    paymaster: Optional[AddressType] = None
    factory_deps: Optional[List[Hash32]] = Field(None, alias="factoryDeps")
    paymaster_input: Optional[bytes] = Field(None, alias="paymasterInput")

    gas_limit: Optional[GasLimit] = Field(None, alias="ergsLimit")
    type: int = Field(TransactionType.ZKSYNC.value, alias="txType", const=True)
    max_fee: Optional[int] = Field(None, alias="maxFeePerErg")
    max_priority_fee: Optional[int] = Field(None, alias="maxPriorityFeePerErg")

    aa_signature: Optional[MessageSignature] = None

    def serialize_transaction(self) -> bytes:
        if not (self.signature or self.aa_signature):
            raise SignatureError("Transaction is not signed.")

        to_bytes = (
            lambda val: HexBytes(val).lstrip(b"\x00") if val else HexBytes(b"")
        )  # noqa: E731

        data = [
            to_bytes(self.nonce),
            to_bytes(self.max_priority_fee),
            to_bytes(self.max_fee),
            to_bytes(self.gas_limit),
            to_bytes(self.receiver),
            to_bytes(self.value),
            to_bytes(self.data),
        ]

        if self.signature:
            v, r, s = self.signature
            data += [to_bytes(v - 27), to_bytes(r), to_bytes(s)]
        else:
            # account abstraction support
            data += [to_bytes(self.chain_id), b"", b""]

        data += [
            to_bytes(self.chain_id),
            to_bytes(self.sender),
            to_bytes(self.gas_per_pubdata_byte_limit),
            [to_bytes(v) for v in self.factory_deps] if self.factory_deps else [],
            to_bytes(self.aa_signature),
        ]

        if self.paymaster:
            data += [to_bytes(self.paymaster), to_bytes(self.paymaster_input)]
        else:
            data += []

        return HexBytes(self.type) + rlp.encode(data)

    @property
    def txn_hash(self) -> HexBytes:
        return HexBytes(keccak(self.serialize_transaction()))


class ZKSyncReceipt(ReceiptAPI):
    block_hash: Hash32 = Field(..., alias="blockHash")
    block_number: int = Field(..., alias="blockNumber")
    contract_address: Optional[AddressType] = Field(None, alias="contractAddress")
    gas_price: int = Field(..., alias="effectiveGasPrice")
    sender: AddressType = Field(..., alias="from")
    gas_used: int = Field(..., alias="gasUsed")
    l1_batch_number: int = Field(..., alias="l1BatchNumber")
    l1_batch_tx_index: int = Field(..., alias="l1BatchTxIndex")
    txn_hash: str = Field(..., alias="transactionHash")
    type: int = 0
    transaction: Union[LegacyTransaction, ZKSyncTransaction] = Field(None, exclude=True)

    def total_fees_paid(self) -> int:
        return 0

    def ran_out_of_gas(self) -> bool:
        return False

    def decode_logs(
        self,
        abi: Optional[
            Union[List[Union[EventABI, ContractEvent]], Union[EventABI, ContractEvent]]
        ] = None,
    ) -> Iterator[ContractLog]:
        if abi is None:
            abi = []
        elif not isinstance(abi, (list, tuple)):
            abi = [abi]

        abi += [ERC20_TYPE.events["Transfer"]]
        abi += [CONTRACT_DEPLOYER_TYPE.events["ContractDeployed"]]

        yield from Receipt.decode_logs(self, abi)
        yield from Receipt.decode_logs(self)

    _decode_ds_note = Receipt._decode_ds_note
