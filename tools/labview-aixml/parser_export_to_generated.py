#!/usr/bin/env python3
"""Turn LabVIEW's AIXML export of bats.parser.vi into bats.parser.generated.xml, a document the
AIXML importer accepts (todo: FIFO stand-ins, 2026-10-14).

    python3 parser_export_to_generated.py <bats.parser.xml export> <out.xml>

What it does, each step measured to be necessary with lvai_validate_aixml:
 1. The two FPGA FIFO Write nodes export as <Call target="niFpgaContainer.xnode"> and cannot be
    imported. Each becomes: Constant "FIFO Name" (string), Constant "Data Type" (string),
    To Variant on the element, Call target="FIFO.WRITE.vi" (handshake terminals: FIFO In,
    Element, Input Valid -> Ready for Input, FIFO Out). FIFO.WRITE.vi / FIFO.READ.vi are the
    stand-ins (FIFO.WRITE.xml / FIFO.READ.xml beside this script).
 2. The plain Bundle that joins `reset` and `data.stream` exports with NAMED element inputs and
    imports as a cluster without element names, so the Unbundle By Name after it reads "Cluster
    is invalid or empty" and every downstream wire is void. It becomes a Bundle By Name on a
    typed constant.
 3. A Bundle/Unbundle By Name cannot address a field whose own NAME contains a dot
    (`buffer.length`, `Next.Seq.No`, `recv.time` ...) - "Contains unwired or bad terminal" -
    although nesting via dot (`debug.write`) works. Every By Name node that touches such a field
    is rewritten as positional Unbundle / Bundle nodes with the exact cluster type (field order
    taken from the type literals in the document). Nodes on clusters without dotted names
    (the debug cluster {write, data}) stay By Name.
 4. The message-type Case Structure shows its U8 selectors in hex ("21, 22, 2F"); the importer
    reads decimal, so they are converted ("33, 34, 47").
Generate with lvai_generate_vi panePattern=4815 AFTER lvai_open_file has loaded every subVI the
parser calls (AddOrder ... Trade, add.data.to.buffer, compress.buffer.generated, new.uxx.be,
FIFO.WRITE): the importer resolves Calls to loaded VIs by name, which avoids placeholder stubs
(seven message VIs share one pane signature, so stubs could not be told apart).
"""
import re, sys

def esc(t):
    t = t.replace('\\', '\\\\').replace(':', '\\3A').replace(',', '\\2C').replace('\n', '\\0A')
    return t.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')

FIFOS = {  # export uid of the xnode Call -> (FIFO name, data type text)
    "2473": ("TS-Filter.Command", "orderbook.command.ctl (cluster, 17 fields)"),
    "6532": ("TS-Debug", "array of U64 (4 words, the DEBUG trace record)"),
}
DESC = ("REFERENCE COPY of bats.parser.vi, built 2026-10-14 from its AIXML export. The two FPGA FIFO Write "
        "nodes (handshake interface), which AIXML cannot carry, are replaced by calls to FIFO.WRITE.vi with the "
        "FIFO's configuration wired as constants: FIFO Name and Data Type, Element through To Variant. Everything "
        "else is the exported diagram; typedefs come back as bare clusters and Bundle/Unbundle By Name on dotted "
        "field names became positional Bundle/Unbundle (AIXML limitation). To put the real FIFO nodes back: "
        "replace each FIFO.WRITE.vi call with the FPGA FIFO Method Node (Write) for the named FIFO, wire Element "
        "and Input Valid, read Ready for Input, delete the constants and To Variant.")

def step1_fifos(s):
    def repl(m):
        uid, par, el, iv = m.group('uid'), m.group('par'), m.group('el'), m.group('iv')
        name, dtype = FIFOS[uid]; b = int(uid) * 10 + 90000
        return (f'<Constant _name="FIFO Name" outputs="value:{b}.value" type="string" uid="{b}" uid_parent="{par}" value="{esc(name)}"/>\n'
                f'          <Constant _name="Data Type" outputs="value:{b+1}.value" type="string" uid="{b+1}" uid_parent="{par}" value="{esc(dtype)}"/>\n'
                f'          <Node _name="To Variant" inputs="anything:{el}" outputs="Variant:{b+2}.Variant" uid="{b+2}" uid_parent="{par}"/>\n'
                f'          <Call inputs="FIFO In:,FIFO Name:{b}.value,Data Type:{b+1}.value,Element:{b+2}.Variant,Input Valid:{iv}" outputs="FIFO Out:,Ready for Input:" target="FIFO.WRITE.vi" uid="{uid}" uid_parent="{par}"/>')
    pat = re.compile(r'<Call inputs="FIFO In:,Element:(?P<el>[^,]*),Input Valid:(?P<iv>[^"]*)" outputs="Ready for Input:,FIFO Out:" target="niFpgaContainer.xnode" uid="(?P<uid>\d+)" uid_parent="(?P<par>\w+)"/>')
    s, k = pat.subn(repl, s); assert k == 2, k
    return s.replace('<VI _name="bats.parser.vi" description="">', f'<VI _name="bats.parser.generated.vi" description="{esc(DESC)}">', 1)

def step2_bundle(s):
    ds = re.search(r'<Control _name="data.stream"[^>]*type="([^"]*)"[^>]*value="([^"]*)"', s)
    old = '  <Node _name="Bundle" inputs="reset:1586.value,data.stream:3507.value,cluster:" outputs="output cluster:6105.output cluster" uid="6105" uid_parent="root"/>'
    new = (f'  <Constant _name="reset + data.stream" outputs="value:6106.value" type="cluster{{bool.reset,{ds.group(1)}.data.stream}}" uid="6106" uid_parent="root" value="[false,{ds.group(2)}]"/>\n'
           '  <Node _name="Bundle By Name" fields="reset,data.stream" inputs="reset:1586.value,data.stream:3507.value,input cluster:6106.value" outputs="output cluster:6105.output cluster" uid="6105" uid_parent="root"/>')
    assert s.count(old) == 1; return s.replace(old, new)

def fields_of(tl):
    body = tl[8:-1]; out = []; depth = 0; cur = ''
    for ch in body:
        if ch == '{': depth += 1
        if ch == '}': depth -= 1
        if ch == ',' and depth == 0: out.append(cur); cur = ''
        else: cur += ch
    out.append(cur); res = []
    for item in out:
        if '}' in item: t, n = item.rsplit('}', 1); t += '}'; n = n[1:]
        else: t, n = item.split('.', 1)
        res.append((n, t))
    return res

def step3_positional(s):
    TYPES = {'S': fields_of(re.search(r'<Constant _name="BATS.Parser.State.Data"[^>]*type="([^"]*)"', s).group(1)),
             'D': fields_of(re.search(r'<Control _name="data.stream"[^>]*type="([^"]*)"', s).group(1)),
             'C': fields_of(re.search(r'<Constant _name="OrderBook.Command"[^>]*type="([^"]*)"', s).group(1)),
             'RD': fields_of(re.search(r'<Constant _name="reset \+ data.stream"[^>]*type="([^"]*)"', s).group(1))}
    TYPES['G'] = fields_of(dict(TYPES['S'])['debug'])
    uid = [300000]
    def nid(): uid[0] += 1; return str(uid[0])
    def sub_kind(kind, f):
        t = dict(TYPES[kind])[f]
        for k, v in TYPES.items():
            if t.startswith('cluster{') and v == fields_of(t): return k
        raise Exception(f + ' is not a known cluster')
    def split_path(kind, pth):
        for n, _ in sorted(TYPES[kind], key=lambda x: -len(x[0])):
            if pth == n: return n, None
            if pth.startswith(n + '.'): return n, pth[len(n) + 1:]
        raise Exception(f'{pth} not in {kind}')
    def attr(line, key):
        m = re.search(key + r'="([^"]*)"', line); return m.group(1) if m else ''
    def pairs(v): return [(t.split(':', 1)[0], t.split(':', 1)[1]) for t in v.split(',') if t]
    out = []
    def emit_unbundle(net, kind, wanted, par):
        fl = TYPES[kind]; direct = {}; nested = {}
        for pth, onet in wanted.items():
            f, rest = split_path(kind, pth)
            if rest is None: direct[f] = onet
            else: nested.setdefault(f, {})[rest] = onet
        elem = {f: direct.get(f, f'{nid()}.{f}' if f in nested else '') for f, _ in fl}
        out.append(f'<Node _name="Unbundle" inputs="cluster:{net}" outputs="{",".join("element:" + elem[f] for f, _ in fl)}" uid="{nid()}" uid_parent="{par}"/>')
        for f, sub in nested.items(): emit_unbundle(elem[f], sub_kind(kind, f), sub, par)
    def emit_bundle(base, kind, given, onet, par):
        fl = TYPES[kind]; direct = {}; nested = {}
        for pth, inet in given.items():
            f, rest = split_path(kind, pth)
            if rest is None: direct[f] = inet
            else: nested.setdefault(f, {})[rest] = inet
        keep = {f: ('' if f in direct else f'{nid()}.{f}') for f, _ in fl}
        out.append(f'<Node _name="Unbundle" inputs="cluster:{base}" outputs="{",".join("element:" + keep[f] for f, _ in fl)}" uid="{nid()}" uid_parent="{par}"/>')
        final = {}
        for f, _ in fl:
            if f in direct: final[f] = direct[f]
            elif f in nested: final[f] = emit_bundle(keep[f], sub_kind(kind, f), nested[f], f'{nid()}.{f}', par)
            else: final[f] = keep[f]
        out.append(f'<Node _name="Bundle" inputs="{",".join("element:" + final[f] for f, _ in fl)},cluster:{base}" outputs="output cluster:{onet}" uid="{nid()}" uid_parent="{par}"/>')
        return onet
    new = []
    for line in s.split('\n'):
        st = line.strip()
        if not (st.startswith('<Node _name="Unbundle By Name"') or st.startswith('<Node _name="Bundle By Name"')):
            new.append(line); continue
        fields = attr(line, 'fields').split(','); ins = pairs(attr(line, 'inputs')); outs = pairs(attr(line, 'outputs'))
        par = attr(line, 'uid_parent'); indent = line[:len(line) - len(line.lstrip())]
        cands = [k for k, v in TYPES.items() if all(any(p == n or p.startswith(n + '.') for n, _ in v) for p in fields)]
        if cands == ['G'] and all('.' not in p for p in fields):
            new.append(line); continue
        kind = [k for k in ('RD', 'S', 'C', 'D', 'G') if k in cands][0]
        out.clear()
        if st.startswith('<Node _name="Unbundle By Name"'):
            emit_unbundle(dict(ins)['input cluster'], kind, {k: v for k, v in outs if v}, par)
        else:
            emit_bundle(dict(ins)['input cluster'], kind, {k: v for k, v in ins if k != 'input cluster' and v}, dict(outs)['output cluster'], par)
        new.extend(indent + l for l in out)
    return '\n'.join(new)

def step4_hex_selectors(s):
    m = re.search(r'(<Structure _name="Case Structure" selectin="364.unsigned 8bit integer" uid="925".*?)(\n\s*</Structure>)', s, re.S)
    block = m.group(1)
    def fix(mm):
        parts = [x.strip() for x in mm.group(1).split('\\2C')]
        return 'selector="' + '\\2C '.join('Default' if x == 'Default' else str(int(x, 16)) for x in parts) + '"'
    return s.replace(block, re.sub(r'selector="([^"]*)"', fix, block))

if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    s = open(src, encoding='utf-8').read()
    s = step4_hex_selectors(step3_positional(step2_bundle(step1_fifos(s))))
    open(dst, 'w', encoding='utf-8', newline='\n').write(s)
    print('written', dst)
