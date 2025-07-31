from pysv import (
    DataType,
    compile_lib,
    generate_sv_binding,
    sv
)
from cboe_pitch.pitch24 import FieldConverter
from collections import deque
from enum import Enum
import math
from pathlib import Path
import sys
import tomllib
from typing import Dict, List




class OBCommand(object):
    @sv()
    def __init__(self):
        self._cmd_type = 0
        self._cmd_side = 0
        self._cmd_orderid = 0
        self._cmd_quantity = 0

        self._cmd_symbol = 0
        self._cmd_price = 0
        self._cmd_executed_qty = 0
        self._cmd_canceled_qty = 0

        self._cmd_remaining_qty = 0
        self._cmd_seconds = 0
        self._cmd_nanoseconds = 0
        self._cmd_add = 0

        self._cmd_edit = 0
        self._cmd_remove = 0
        self._cmd_seq_no = 0

    # Creators
    def from_dict(self, in_dict):
        self._cmd_type = in_dict['cmd_type']
        self._cmd_side = in_dict['cmd_side']
        self._cmd_orderid = in_dict['cmd_orderid']
        self._cmd_quantity = in_dict['cmd_quantity']

        self._cmd_symbol = in_dict['cmd_symbol']
        self._cmd_price = in_dict['cmd_price']
        self._cmd_executed_qty = in_dict['cmd_executed_qty']
        self._cmd_canceled_qty = in_dict['cmd_canceled_qty']

        self._cmd_remaining_qty = in_dict['cmd_remaining_qty']
        self._cmd_seconds = in_dict['cmd_seconds']
        self._cmd_nanoseconds = in_dict['cmd_nanoseconds']
        self._cmd_add = in_dict['cmd_add']

        self._cmd_edit = in_dict['cmd_edit']
        self._cmd_remove = in_dict['cmd_remove']
        self._cmd_seq_no = in_dict['cmd_seq_no']

    # Properties

    # Command Type
    @sv(return_type=DataType.UByte)
    def cmd_type(self) -> int:
        return self._cmd_type
    def cmd_type_str(self) -> str:
        if self._cmd_type == 0:
            return 'Time'
        elif self._cmd_type == 1:
            return 'AddOrder'
        elif self._cmd_type == 2:
            return 'OrderExecuted'
        elif self._cmd_type == 3:
            return 'OrderExecutedAtPrice'
        elif self._cmd_type == 4:
            return 'ReduceSize'
        elif self._cmd_type == 5:
            return 'ModifyOrder'
        elif self._cmd_type == 6:
            return 'DeleteOrder'
        elif self._cmd_type == 7:
            return 'GetEverything'
        elif self._cmd_type == 8:
            return 'GetAllOrders'
        elif self._cmd_type == 9:
            return 'GetTop'

    # Side
    @sv(return_type=DataType.UByte)
    def cmd_side(self) -> int:
        return self._cmd_side
    def cmd_side_str(self) -> str:
        return 'B' if self._cmd_side == ord('B') else 'S'

    # OrderId
    @sv(return_type=DataType.ULongInt)
    def cmd_orderid(self) -> int:
        return self._cmd_orderid
    @sv(return_type=DataType.String)
    def cmd_orderid_str(self) -> str:
        return FieldConverter.u64_to_orderid(self._cmd_orderid)

    # Quantity
    @sv(return_type=DataType.UInt)
    def cmd_quantity(self) -> int:
        return self._cmd_quantity

    # Symbol
    @sv(return_type=DataType.ULongInt)
    def cmd_symbol(self) -> int:
        return self._cmd_symbol
    @sv(return_type=DataType.String)
    def cmd_symbol_str(self) -> str:
        return FieldConverter.u64_to_symbol(self._cmd_symbol)

    # Price
    @sv(return_type=DataType.Float)
    def cmd_price(self) -> int:
        return self._cmd_price
    def cmd_price_str(self) -> str:
        return f'{self._cmd_price:.4f}'

    # Executed Quantity
    @sv(return_type=DataType.UInt)
    def cmd_executed_qty(self) -> int:
        return self._cmd_executed_qty
    def cmd_executed_qty_str(self) -> str:
        return f'{self._cmd_executed_qty}'

    # Canceled Quantity
    @sv(return_type=DataType.UInt)
    def cmd_canceled_qty(self) -> int:
        return self._cmd_canceled_qty
    def cmd_canceled_qty_str(self) -> str:
        return f'{self._cmd_canceled_qty}'

    # Remaining Quantity
    @sv(return_type=DataType.UInt)
    def cmd_remaining_qty(self) -> int:
        return self._cmd_remaining_qty
    def cmd_remaining_qty_str(self) -> str:
        return f'{self._cmd_remaining_qty}'

    # Seconds
    @sv(return_type=DataType.ULongInt)
    def cmd_seconds(self) -> int:
        return self._cmd_seconds
    def cmd_seconds_str(self) -> str:
        return f'{self._cmd_seconds}'

    # Nanoseconds
    @sv(return_type=DataType.ULongInt)
    def cmd_nanoseconds(self) -> int:
        return self._cmd_nanoseconds
    def cmd_nanoseconds_str(self) -> str:
        return f'{self._cmd_nanoseconds}'

    # Operation (Op)
    @sv(return_type=DataType.Bit)
    def cmd_add(self) -> bool:
        return self._cmd_add

    @sv(return_type=DataType.Bit)
    def cmd_edit(self) -> bool:
        return self._cmd_edit

    @sv(return_type=DataType.Bit)
    def cmd_remove(self) -> bool:
        return self._cmd_remove

    def cmd_op_str(self) -> str:
        if self._cmd_add is True:
            return 'add'
        if self._cmd_edit is True:
            return 'edit'
        if self._cmd_remove is True:
            return 'remove'

    # Sequence Number (No.)
    @sv(return_type=DataType.UInt)
    def cmd_seq_no(self) -> int:
        return self._cmd_seq_no
    def cmd_seq_no_str(self) -> str:
        return f'{self._cmd_seq_no}'

    @sv(return_type=DataType.String)
    def to_str(self) -> str:
        ob_str = '['
        ob_str += f"'{self.cmd_type_str()},'"
        ob_str += f"'{self.cmd_side_str()},'"
        ob_str += f"'{self.cmd_orderid_str()},'"
        ob_str += f"{self.cmd_quantity()},"
        ob_str += f"'{self.cmd_symbol_str()}',"
        ob_str += f"{self.cmd_price_str()},"
        ob_str += f"{self.cmd_executed_qty_str()},"
        ob_str += f"{self.cmd_canceled_qty_str()},"
        ob_str += f"{self.cmd_remaining_qty_str()},"
        ob_str += f"{self.cmd_seconds_str()},"
        ob_str += f"{self.cmd_nanoseconds_str()},"
        ob_str += f"'{self.cmd_op_str()}',"
        ob_str += f"{self.cmd_seq_no_str()},"
        ob_str += ']'
        return ob_str


class FilterBench(object):
    @sv(path_or_str=DataType.String,
        backup_path=DataType.String,
        clock_period=DataType.Int)
    def __init__(self,
                 path_or_str: str,
                 backup_path: str = None,
                 clock_period: int = None):
        toml_file = None
        self._config_file_name = "<raw string>"
        self._clock_period = clock_period

        try:
            if Path(path_or_str).exists() is True:
                self._config_file_name = path_or_str
                with open(Path(path_or_str), mode="rb") as fin:
                    toml_file = tomllib.load(fin)
            elif Path(backup_path).exists() is True:
                self._config_file_name = backup_path
                with open(Path(backup_path), mode="rb") as fin:
                    toml_file = tomllib.load(fin)
        except OSError as ose:
            print(f'Config is a string')
            print('-'*80); sys.stdout.flush()
            toml_file = tomllib.loads(path_or_str)

        if toml_file is None:
            self.LOG_NOW('Exception')
            raise Exception(f'Failed to load config from {path_or_str}')

        try:
            self._name = toml_file['name']
            self._description = toml_file['description']
            self._watch_list = toml_file['watchlist']
            self._number_of_messages = toml_file['generator']['number_of_messages']

            self._securities_gen = []
            for security in toml_file['security']:
                sec_gen_dict = {}
                sec_gen_dict['symbol'] = security['symbol']
                if 'weight' in security:
                    sec_gen_dict['weight'] = security['weight']
                else:
                    sec_gen_dict['weight'] = math.nan
                if 'book_size_range' in security:
                    sec_gen_dict['book_size_range'] = security['book_size_range']
                else:
                    sec_gen_dict['book_size_range'] = 10
                if 'price_range' in security:
                    sec_gen_dict['price_range'] = security['price_range']
                else:
                    sec_gen_dict['price_range'] = [75.00, 125.00]
                if 'size_range' in security:
                    sec_gen_dict['size_range'] = security['size_range']
                else:
                    sec_gen_dict['size_range'] = [25, 200]

                self._securities_gen.append(sec_gen_dict)
                self._orderids = set()

        except Exception as ex:
            print(f'Exception caught in FilterBench.__init__:\n{ex}')
            print('-'*80); sys.stdout.flush()

        #print(f'---+++****' * 80); sys.stdout.flush()
        self._commands = deque()
        ob_cmds = self.gen_messages(toml_file)
        self._commands.extend(ob_cmds)
        #print(f'toml_file: {toml_file}')
        # Index by OrderID + Seconds + Nanoseconds
        self._msgs = {}
        self._expected_msgs_count = 0

    @sv(return_type=DataType.Int)
    def get_expected_msgs_count(self) -> int:
        return self._expected_msgs_count


    @sv()
    def gen_messages(self, toml_file):
        my_cmds = deque()

        class CmdType(Enum):
            Time = 0
            AddOrder = 1
            OrderExecuted = 2
            OrderExecutedAtPrice = 3
            ReduceSize = 4
            ModifyOrder = 5
            DeleteOrder = 6
            GetEverything = 7
            GetAllOrders = 8
            GetTop = 9

        def gen_cmd(cmd_type: str,
                    cmd_side: str,
                    cmd_orderid: str,
                    cmd_quantity: int,
                    cmd_symbol: int,
                    cmd_price: int,
                    cmd_executed_qty: int,
                    cmd_canceled_qty: int,
                    cmd_remaining_qty: int,
                    cmd_seconds: int,
                    cmd_nanoseconds: int,
                    cmd_add: int,
                    cmd_edit: int,
                    cmd_remove: int,
                    cmd_seq_no: int
                    ):
            out_cmd = {}
            out_cmd['cmd_type'] = CmdType[cmd_type].value
            out_cmd['cmd_side'] = 0x42 if cmd_side == 'B' else 0x53
            out_cmd['cmd_orderid'] = FieldConverter.orderid_to_u64(cmd_orderid)
            out_cmd['cmd_quantity'] = cmd_quantity

            out_cmd['cmd_symbol'] = FieldConverter.symbol_to_u64(cmd_symbol)
            out_cmd['cmd_price'] = cmd_price
            out_cmd['cmd_executed_qty'] = cmd_executed_qty
            out_cmd['cmd_canceled_qty'] = cmd_canceled_qty

            out_cmd['cmd_remaining_qty'] = cmd_remaining_qty
            out_cmd['cmd_seconds'] = cmd_seconds
            out_cmd['cmd_nanoseconds'] = cmd_nanoseconds
            out_cmd['cmd_add'] = cmd_add

            out_cmd['cmd_edit'] = cmd_edit
            out_cmd['cmd_remove'] = cmd_remove
            out_cmd['cmd_seq_no'] = cmd_seq_no
            return out_cmd

        # Read messages from config
        # or use generator
        if 'messages' in toml_file:
            #print(f'Using messages from config file')
            ob_cmds = []
            field_map = {}
            for idx, val in enumerate(toml_file['messages']['csv'][0]):
                #print(f' {val} = {idx}')
                field_map[val] = idx

            # cmd_type = get_field('Type')
            for msg in toml_file['messages']['csv'][1:]:
                #print(f'OrderId: {msg[field_map["OrderId"]]}')
                my_cmds.append( gen_cmd(cmd_type=msg[field_map['Type']],
                                        cmd_side=msg[field_map['Side']],
                                        cmd_orderid=msg[field_map['OrderId']],
                                        cmd_quantity=msg[field_map['Quantity']],
                                        cmd_symbol=msg[field_map['Symbol']],
                                        cmd_price=msg[field_map['Price']],
                                        cmd_executed_qty=msg[field_map['Exe Quantity']],
                                        cmd_canceled_qty=msg[field_map['Can Quantity']],
                                        cmd_remaining_qty=msg[field_map['Rem Quantity']],
                                        cmd_seconds=msg[field_map['Seconds']],
                                        cmd_nanoseconds=msg[field_map['Seconds']],
                                        cmd_add=msg[field_map['Op']] == 'add',
                                        cmd_edit=msg[field_map['Op']] == 'edit',
                                        cmd_remove=msg[field_map['Op']] == 'remove',
                                        cmd_seq_no=msg[field_map['SeqNo']]
                                        ) )
                #print(f'my_cmds[0]: {my_cmds[0]}')
        else:
            print(f'Using message generator')

        return my_cmds

    @sv(msg=DataType.String)
    def LOG_NOW(self, msg: str):
        print(msg)
        sys.stdout.flush()

    @sv(return_type=DataType.String)
    def name(self) -> str:
        return self._name

    @sv(return_type=DataType.String)
    def description(self) -> str:
        return self._description

    @sv(return_type=DataType.String)
    def watch_list(self) -> List[str]:
        return self._watch_list

    @sv(return_type=DataType.Int)
    def number_of_messages(self) -> int:
        return self._number_of_messages

    @sv(return_type=DataType.String)
    def get_config_file(self) -> str:
        return self._config_file_name

    @sv(return_type=DataType.String)
    def print_header(self) -> str:
        watch_list = '\n'.join(['  - ' + x for x in self._watch_list])
        securities_gen = '\n'.join([ str(x) for x in self._securities_gen])
        return f"""\
+----------------------------------------------------------------------------+
{self.name()}
--
{self.description()}
--
Watchlist:
{watch_list}
--
Generator Options:
# of messages: {self.number_of_messages()}
--
Generator.Securities:
{securities_gen}
+----------------------------------------------------------------------------+\
"""

    # WatchList Section
    @sv(return_type=DataType.Int)
    def watchlist_get_size(self) -> int:
        return len(self._watch_list)

    @sv(idx=DataType.Int,
        return_type=DataType.ULongInt)
    def watchlist_get_item(self, idx: int) -> int:
        right_padded = self._watch_list[idx] + ((8 - len(self._watch_list[idx])) * " ")
        val = int.from_bytes(right_padded.encode(), "big")
        return val

    @sv(idx=DataType.Int,
        return_type=DataType.String)
    def watchlist_get_item_str(self, idx: int) -> str:
        return self._watch_list[idx]

    # Command Section
    @sv(in_ob_cmd=DataType.Object)
    def get_next_command(self, in_ob_cmd) -> None:
        in_ob_cmd.from_dict(self._commands.popleft())

    @sv(return_type=DataType.Bit)
    def has_more_commands(self) -> bool:
        return len(self._commands) > 0


    @sv(in_ob_cmd=OBCommand, in_time_ns=DataType.Int)
    def log_command_send(self,
                         in_ob_cmd: 'OBCommand',
                         in_time_ns: int) -> None:
        #self.LOG_NOW(f'Logging_send: {in_ob_cmd.to_str()}')
        msg_key = f'{in_ob_cmd.cmd_orderid_str()}-{in_ob_cmd.cmd_seq_no_str()}'
        self._msgs[msg_key] = {'ob_cmd': in_ob_cmd, 'sent_time': in_time_ns}

        # Should this message pass through the filter?
        if in_ob_cmd.cmd_type_str() == 'AddOrder':
            #self.LOG_NOW(f'  --  AddOrder: {in_ob_cmd.cmd_symbol_str()} --')
            if in_ob_cmd.cmd_symbol_str() in set(self._watch_list):
                self._expected_msgs_count += 1
                self._orderids.add(in_ob_cmd.cmd_orderid_str())
                #self.LOG_NOW(f'  --  self._orderids: {len(self._orderids)}')
        else:
            #self.LOG_NOW('  --  Other type --')
            if in_ob_cmd.cmd_orderid_str() in self._orderids:
                self._expected_msgs_count += 1

    @sv(in_orderid=DataType.ULongInt,
        in_seq_no=DataType.ULongInt,
        in_time_ns=DataType.Int)
    def log_command_receive(self,
                            in_orderid: int,
                            in_seq_no: int,
                            in_time_ns: int) -> None:
        in_orderid_str = FieldConverter.u64_to_orderid(in_orderid)
        in_seq_no_str = f'{in_seq_no}'

        msg_key = f'{in_orderid_str}-{in_seq_no}'
        #self.LOG_NOW(f'Logging_recv: {msg_key}')

        self._msgs[msg_key]['recv_time'] = in_time_ns


    @sv(return_type=DataType.String)
    def get_results(self):
        results = """\
---------------------
Results of benchmark:
---------------------

"""
        results += """\
-------------------------
Log of messages
-------------------------
"""

        # TODO: Calculate benchmarks using clock rate
        results += '\n'
        results += f'Clock Period: {self._clock_period}ns\n'
        results += '\n'

        for key, val in self._msgs.items():
            # Does message have a received time?
            if 'recv_time' in val:
                [oid, seq_no] = key.split('-')
                delta = val['recv_time'] - val['sent_time']
                results += f'  {oid}:{seq_no} Delta: {delta}ns\n'
        return results


class MyList(object):
    @sv()
    def __init__(self):
        self._data = []

    @sv()
    def get_idx(self, idx):
        return self._data[idx]

    @sv()
    def set_idx(self, idx, value):
        if len(self._data) > idx:
            self._data[idx] = value

    @sv()
    def append(self, value):
        self._data.append(value)

    @sv(in_list=DataType.Object)
    def append_list(self, in_list):
        self._data.extend(in_list)

    @sv(in_list=DataType.Object)
    def prepend_list(self, in_list):
        self._data = in_list + self._data[:]

    @sv()
    def replace_list(self, in_py_list):
        self._data = in_py_list

    @sv()
    def get_length(self):
        return len(self._data)

    @sv()
    def get_num_words(self):
        return ((len(self._data) // 8) + (len(self._data) % 8 > 0))

    @sv()
    def is_aligned(self):
        return (len(self._data) % 8 == 0)

    @sv(index=DataType.Int,
        return_type=DataType.ULongInt)
    def get_word(self, index):
        final_word = 0
        try:
            data_to_copy = self._data.copy()

            start_idx = index * 8
            stop_idx = start_idx + 8
            if start_idx + 8 > len(data_to_copy):
                stop_idx = len(data_to_copy)

            for i in range(start_idx, stop_idx):
                final_word = (final_word << 8) | data_to_copy[i]

            num_zeros = 8 - (stop_idx - start_idx)
            # Add padding
            for i in range(num_zeros):
                final_word = (final_word << 8) | 0

        except Exception as EX:
            print(f'Exception in MyList.get_word(..): {ex}')
            sys.stdout.flush()

        return final_word

    @sv(index=DataType.Int,
        return_type=DataType.UInt)
    def get_byte_enables(self, index):
        start_idx = index * 8
        stop_idx = start_idx + 8
        if start_idx + 8 > len(self._data):
            stop_idx = len(self._data)

        num_zeros = 8 - (stop_idx - start_idx)
        print(f'num_zeroes: {num_zeros}')
        casted = (0xff << num_zeros) & 0xf
        print(f'casted: {hex(casted)} - {bin(casted)}')
        return (0xff << num_zeros) & 0xff

    @sv()
    def from_array(self, in_list):
        self._data = in_list

    @sv(return_type=DataType.Int)
    def to_array(self) -> int:
        return self._data

    @sv(no_x=DataType.Int,
            return_type=DataType.String)
    def to_str(self, no_x=False):
        if hasattr(self, '_data') is False:
            return '[]'
        elif self._data is None:
            return '[]'
        try:
            hdr = '0x'
            if no_x is True:
                hdr = ''
            res = '[' + ' '.join([ str.format('{}{:02X}', hdr, x) for x in self._data]) + ']'
        except Exception as ex:
            print(f'Exception in MyList.get_str(...): {ex}')
            sys.stdout.flush()
        return res

#def log_cmd(in_ob_cmd: OBCommand) -> None:

##############################################################################
# PYSV Related functions
##############################################################################
def compile(compile: bool = True, binding: bool = True):
    compile=True
    binding=True
    # compile the a shared_lib into build folder
    # lib_name='pysv'
    # release_build=False
    # clean_up_build=True
    # add_sys_path=False # Whether to add system path
    if compile is True:
        lib_path = compile_lib([MyList,
                                OBCommand,
                                FilterBench], cwd="build")

    # generate SV binding
    # pkg_name='pysv'
    # pretty_print=True
    #filename='out_sv_file.sv'
    if binding is True:
        generate_sv_binding([MyList,
                             OBCommand,
                             FilterBench], filename="pysv_pkg.sv")

if __name__ == "__main__":
    compile()
