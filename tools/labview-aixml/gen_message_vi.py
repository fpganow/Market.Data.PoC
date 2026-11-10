#!/usr/bin/env python3
"""Emit AIXML for a Cboe PITCH message-type VI in the style of AddOrder.vi.
Usage: gen_message_vi.py <spec name> <out.xml> <stub name> [<vi name>] [--unscaled] [--shift-add]

<vi name> defaults to <spec name>.vi (use e.g. AddOrder.generated.vi).  Short-message
prices (2 implied decimals) are multiplied by 100 so every price carries 4 implied decimals
like the long variants (todo.txt item 9); --unscaled leaves them as they arrive.  All VIs use
the 12-item enum (Trade = 10, Unsupported = 11), see orderbook.command.type.ctl."""
import sys, json

ENUM_CHOICES = ["Time","AddOrder","OrderExecuted","OrderExecutedAtPrice","ReduceSize","ModifyOrder","DeleteOrder","Get.Everything","Get.All.Orders","Get.Top"]
ENUM_EXT = ENUM_CHOICES + ["Trade","Unsupported"]
CLUSTER_ORDER = ["type","side","orderId ","quantity","symbol","price","executed.qty","canceled.qty","remaining.qty","seconds","nanoseconds","Add","Edit","Remove","seq no","recv.time","parse.time"]
CLUSTER_TYPES = ["ENUM","uint8","uint64","uint32","uint64","uint64","uint32","uint32","uint32","uint64","uint64","bool","bool","bool","uint32","uint64","uint64"]
CONV = {  # conv -> (node name, output terminal, result type)
    "u8":  ("To Unsigned Byte Integer", "unsigned 8bit integer", "uint8"),
    "u16": ("To Unsigned Word Integer", "unsigned 16bit integer", "uint16"),
    "u32": ("To Unsigned Long Integer", "unsigned 32bit integer", "uint32"),
    "u64": ("To Unsigned Quad Integer", "unsigned 64bit integer", "uint64"),
}
DEF = "[0,0,0,0,0,0,0,0,0,0,0,false,false,false,0,0,0]"
PRICE_SCALE = 100   # short-variant price multiplier; "--unscaled" sets it to 1
SHIFT_ADD = False   # "--shift-add": build the x100 as (p<<6)+(p<<5)+(p<<2) on U32 instead of a U64 Multiply

# field: (cluster field, start, length, target type) ; target type decides the converter chain.
SPECS = {
 "AddOrder": dict(desc="Cboe PITCH Add Order (0x21 long, 0x22 short, 0x2F expanded) -> orderbook.command: type AddOrder, orderId, side, quantity, symbol (8 chars, space padded; 6-char symbols read as 8 bytes, masked and padded so they are not byte-reversed), price (short price x100 so all prices have 4 implied decimals), nanoseconds, Add. Replaces AddOrder.vi (todo.txt items 4 and 9).",
    ext_enum=True, type_value=1, flags={"Add": True},
    frames=[("33", True,  [("side",14,1,"uint8"), ("quantity",15,4,"uint32"), ("symbol",19,6,"sym6"), ("price",25,8,"uint64")], "AddOrder (long)"),
            ("34", False, [("side",14,1,"uint8"), ("quantity",15,2,"uint32"), ("symbol",17,6,"sym6"), ("price",23,2,"price2")], "AddOrder (short)"),
            ("47", False, [("side",14,1,"uint8"), ("quantity",15,4,"uint32"), ("symbol",19,8,"uint64"), ("price",27,8,"uint64")], "AddOrder (expanded)")]),
 "ModifyOrder": dict(desc="Cboe PITCH Modify Order (0x27 long, 0x28 short) -> orderbook.command: type ModifyOrder, orderId, new quantity, new price (short price x100 so all prices have 4 implied decimals), nanoseconds, Edit.",
    ext_enum=True, type_value=5, flags={"Edit": True},
    frames=[("39", True, [("quantity",14,4,"uint32"), ("price",18,8,"uint64")], "ModifyOrder (long)"),
            ("40", False, [("quantity",14,2,"uint32"), ("price",16,2,"price2")], "ModifyOrder (short)")]),
 "DeleteOrder": dict(desc="Cboe PITCH Delete Order (0x29) -> orderbook.command: type DeleteOrder, orderId, nanoseconds, Remove.",
    ext_enum=True, type_value=6, flags={"Remove": True}, frames=[]),
 "Trade": dict(desc="Cboe PITCH Trade (0x2A long, 0x2B short, 0x30 expanded) -> orderbook.command: type Trade (enum value 10, add Trade=10 and Unsupported=11 to orderbook.command.type.ctl), orderId, side, quantity, symbol (8 chars, space padded), price, nanoseconds. Short price x100 so all prices have 4 implied decimals.",
    ext_enum=True, type_value=10, flags={},
    frames=[("42", True,  [("side",14,1,"uint8"), ("quantity",15,4,"uint32"), ("symbol",19,6,"sym6"), ("price",25,8,"uint64")], "Trade (long)"),
            ("43", False, [("side",14,1,"uint8"), ("quantity",15,2,"uint32"), ("symbol",17,6,"sym6"), ("price",23,2,"price2")], "Trade (short)"),
            ("48", False, [("side",14,1,"uint8"), ("quantity",15,4,"uint32"), ("symbol",19,8,"uint64"), ("price",27,8,"uint64")], "Trade (expanded)")]),
 "OrderExecuted": dict(desc="Cboe PITCH Order Executed (0x23) and Order Executed at Price/Size (0x24) -> orderbook.command: type OrderExecuted or OrderExecutedAtPrice, orderId, executed.qty, remaining.qty and price (0x24 only), nanoseconds, Edit.",
    ext_enum=True, type_value=None, flags={"Edit": True},
    frames=[("35", True,  [("type",None,None,"enum:2"), ("executed.qty",14,4,"uint32"), ("remaining.qty",None,None,"const:uint32:0"), ("price",None,None,"const:uint64:0")], "OrderExecuted"),
            ("36", False, [("type",None,None,"enum:3"), ("executed.qty",14,4,"uint32"), ("remaining.qty",18,4,"uint32"), ("price",30,8,"uint64")], "OrderExecutedAtPriceSize")]),
}

def main():
    global PRICE_SCALE, SHIFT_ADD
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--unscaled" in sys.argv: PRICE_SCALE = 1
    if "--shift-add" in sys.argv: SHIFT_ADD = True
    name, out, stub = args[0], args[1], args[2]
    viname = args[3] if len(args) > 3 else f"{name}.vi"
    sp = SPECS[name]
    choices = ENUM_EXT if sp["ext_enum"] else ENUM_CHOICES
    enum_t = "uint8{" + ",".join(choices) + "}"
    ctypes = [enum_t if t == "ENUM" else t for t in CLUSTER_TYPES]
    cl_t = "cluster{" + ",".join(f"{t}.{f}" for t, f in zip(ctypes, CLUSTER_ORDER)) + "}"
    uid = [1100]
    def nid():
        uid[0] += 1; return str(uid[0])
    L = []   # lines
    def const(nm, typ, val, parent):
        u = nid(); L.append(f'  <Constant _name="{nm}" outputs="value:{u}.value" type="{typ}" uid="{u}" uid_parent="{parent}" value="{val}"/>'); return f"{u}.value"
    def call(bufnet, start, length, parent):
        s = const("Start.Idx", "uint8", start, parent); l = const("Length", "uint8", length, parent); u = nid()
        L.append(f'  <Call inputs="buffer (U64):{bufnet},Start.Idx:{s},Length:{l},Big.Endian?:" outputs="Out.Value U64:{u}.Out.Value U64" target="{stub}" uid="{u}" uid_parent="{parent}"/>')
        return f"{u}.Out.Value U64"
    def conv(net, kind, parent):
        n, o, t = CONV[kind]; u = nid()
        L.append(f'  <Node _name="{n}" inputs="number:{net}" outputs="{o}:{u}.{o}" uid="{u}" uid_parent="{parent}"/>'); return f"{u}.{o}"
    def extract(bufnet, start, length, target, parent):
        """returns net of the value converted to the cluster type"""
        if target == "sym6":   # read 8 bytes, keep the low 6 (stream bytes 0-5), pad with two spaces
            raw = call(bufnet, start, 8, parent)
            m1 = const("mask6", "uint64", 281474976710655, parent); u = nid()
            L.append(f'  <Node _name="And" inputs="x:{raw},y:{m1}" outputs="x .and. y?:{u}.x .and. y?" uid="{u}" uid_parent="{parent}"/>')
            pad = const("pad", "uint64", 2314850208468434944, parent); v = nid()
            L.append(f'  <Node _name="Or" inputs="x:{u}.x .and. y?,y:{pad}" outputs="x .or. y?:{v}.x .or. y?" uid="{v}" uid_parent="{parent}"/>')
            return f"{v}.x .or. y?"
        if target == "price2":  # 2-byte price, 2 implied decimals -> x PRICE_SCALE = 4 implied decimals
            if PRICE_SCALE == 1:
                return conv(conv(call(bufnet, start, 2, parent), "u16", parent), "u64", parent)
            if SHIFT_ADD:  # x100 = (p<<6)+(p<<5)+(p<<2) on U32: two adders, no DSP (todo.txt item 18, cause A)
                p32 = conv(conv(call(bufnet, start, 2, parent), "u16", parent), "u32", parent)
                parts = []
                for sh in (6, 5, 2):
                    k = const("shift", "int16", sh, parent); u = nid()
                    L.append(f'  <Node _name="Logical Shift" comment="price &lt;&lt; {sh}" inputs="y:{k},x:{p32}" outputs="x &lt;&lt; y:{u}.sh{sh}" uid="{u}" uid_parent="{parent}"/>')
                    parts.append(f"{u}.sh{sh}")
                a = nid(); L.append(f'  <Node _name="Add" comment="p*64 + p*32" inputs="x:{parts[0]},y:{parts[1]}" outputs="x+y:{a}.x+y" uid="{a}" uid_parent="{parent}"/>')
                b = nid(); L.append(f'  <Node _name="Add" comment="+ p*4 = p*100 (2 -> 4 implied decimals)" inputs="x:{a}.x+y,y:{parts[2]}" outputs="x+y:{b}.x+y" uid="{b}" uid_parent="{parent}"/>')
                return conv(f"{b}.x+y", "u64", parent)
            net = conv(conv(call(bufnet, start, 2, parent), "u16", parent), "u64", parent)
            k = const("price scale", "uint64", PRICE_SCALE, parent); u = nid()
            L.append(f'  <Node _name="Multiply" comment="2 -> 4 implied decimals" inputs="x:{net},y:{k}" outputs="x*y:{u}.x*y" uid="{u}" uid_parent="{parent}"/>')
            return f"{u}.x*y"
        raw = call(bufnet, start, length, parent)
        first = {1: "u8", 2: "u16", 4: "u32", 8: "u64"}[length]
        net = conv(raw, first, parent)
        want = {"uint8": "u8", "uint16": "u16", "uint32": "u32", "uint64": "u64"}[target]
        if want != first:
            net = conv(net, want, parent)
        return net

    L.append(f'<VI _name="{viname}" description="{sp["desc"]}">')
    root = "root"
    buf = nid(); L.append(f'  <Control _name="buffer.in" conIdx="11" connection="recommended" outputs="value:{buf}.value" type="array{{uint64.Numeric}}" uid="{buf}" uid_parent="root" value="[0,0,0,0,0,0,0,0,0]"/>')
    bufnet = f"{buf}.value"
    base = const("OrderBook.Command", cl_t, DEF, root)
    byname = {}     # field -> net (undotted, Bundle By Name)
    positional = {} # cluster index -> net (dotted)
    if sp["type_value"] is not None:
        byname["type"] = const("OrderBook Command", enum_t, sp["type_value"], root)
    for f, v in sp["flags"].items():
        byname[f] = const(f, "bool", "true" if v else "false", root)
    tb = conv(call(bufnet, 1, 1, root), "u8", root)                 # type byte
    byname["nanoseconds"] = conv(call(bufnet, 2, 4, root), "u64", root)
    byname["orderId "] = conv(call(bufnet, 6, 8, root), "u64", root)
    frames = sp["frames"]
    if frames:
        cs = nid(); tin = nid()
        outs = [fd[0] for fd in frames[0][2]]     # field order = tunnel order
        L.append(f'  <Structure _name="Case Structure" selectin="{tb}" uid="{cs}" uid_parent="root">')
        L.append(f'    <Tunnel _id="In1" inputs="value:{bufnet}" uid="{tin}" uid_parent="{cs}"/>')
        for sel, isdef, fields, label in frames:
            fr = nid(); selector = f"{sel}\\2C Default" if isdef else sel
            L.append(f'    <CaseFrame selector="{selector}" selectout="" uid="{fr}" uid_parent="{cs}">')
            lb = nid(); L.append(f'      <FreeLabel comment="{label}" uid="{lb}" uid_parent="{fr}"/>')
            tf = nid(); L.append(f'      <Tunnel _id="In1" outputs="value:{tf}.value" uid="{tf}" uid_parent="{fr}"/>')
            fb = f"{tf}.value"
            nets = {}
            for (field, start, length, target) in fields:
                if target.startswith("enum:"):
                    nets[field] = const("type", enum_t, target.split(":")[1], fr)
                elif target.startswith("const:"):
                    _, t, v = target.split(":"); nets[field] = const(field.replace(".", "_"), t, v, fr)
                else:
                    nets[field] = extract(fb, start, length, target, fr)
            for k, field in enumerate(outs, 1):
                tu = nid(); L.append(f'      <Tunnel _id="Out{k}" inputs="value:{nets[field]}" uid="{tu}" uid_parent="{fr}"/>')
            L.append('    </CaseFrame>')
        for k, field in enumerate(outs, 1):
            tu = nid(); L.append(f'    <Tunnel _id="Out{k}" outputs="value:{tu}.value" uid="{tu}" uid_parent="{cs}"/>')
            if "." in field: positional[CLUSTER_ORDER.index(field)] = f"{tu}.value"
            else: byname[field] = f"{tu}.value"
        L.append('  </Structure>')
    cluster_net = base
    if positional:
        ub = nid(); outs_s = ",".join(f"element:{ub}.e{i}" for i in range(17))
        L.append(f'  <Node _name="Unbundle" inputs="cluster:{base}" outputs="{outs_s}" uid="{ub}" uid_parent="root"/>')
        bd = nid(); ins = ",".join(f"element:{positional.get(i, f'{ub}.e{i}')}" for i in range(17)) + ",cluster:"
        L.append(f'  <Node _name="Bundle" comment="dotted fields by position" inputs="{ins}" outputs="output cluster:{bd}.output cluster" uid="{bd}" uid_parent="root"/>')
        cluster_net = f"{bd}.output cluster"
    order = [f for f in CLUSTER_ORDER if f in byname]
    bb = nid()
    fields_attr = ",".join(f.strip() for f in order)
    ins = ",".join(f"{f}:{byname[f]}" for f in order) + f",input cluster:{cluster_net}"
    L.append(f'  <Node _name="Bundle By Name" fields="{fields_attr}" inputs="{ins}" outputs="output cluster:{bb}.output cluster" uid="{bb}" uid_parent="root"/>')
    ind = nid(); L.append(f'  <Indicator _name="OrderBook.Command" conIdx="3" connection="recommended" inputs="value:{bb}.output cluster" type="{cl_t}" uid="{ind}" uid_parent="root" value="{DEF}"/>')
    L.append('</VI>')
    open(out, "w", newline="\r\n").write("\n".join(L) + "\n")
    calls = sum(1 for l in L if "<Call " in l)
    print(f"{name}: {len(L)} lines, {calls} subVI calls")

if __name__ == "__main__":
    main()
