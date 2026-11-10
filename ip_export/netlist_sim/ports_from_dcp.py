#!/usr/bin/env python3
"""Read the top-level port list of a LabVIEW IP-export checkpoint and renumber every
`ctrlind_NN_<name>` reference in the given files to match (matching by <name>).

    python3 ports_from_dcp.py ../NiFpgaAG_poc_ip_kria.dcp tb.sv ../../vivado/mktdata_poc.tcl \
        [--check ../../vivado/ip/NiFpgaIPWrapper_poc_ip_kria.vhd]

LabVIEW numbers the ports differently from one export to the next (seen 2026-10-11: the 14:22
export put the TREADYs first, the 19:37 export went back to DEBUG/CMD/MDEBUG/stream/ip_reset).
The exported .v is encrypted, but the .dcp is a zip whose *_stub.v carries the port names.
--check compares a wrapper VHDL's port list with the .dcp and exits 1 if they differ.
"""
import re, sys, zipfile

def dcp_ports(dcp):
    with zipfile.ZipFile(dcp) as z:
        stub = next(n for n in z.namelist() if n.endswith('_stub.v'))
        text = z.read(stub).decode('latin1')
    return dict(re.findall(r'ctrlind_(\d\d)_(\w+)', text))          # {name: NN} after inversion below

def main():
    args = sys.argv[1:]
    check = None
    if '--check' in args:
        i = args.index('--check'); check = args[i + 1]; del args[i:i + 2]
    dcp, files = args[0], args[1:]
    num_by_name = {name: nn for nn, name in dcp_ports(dcp).items()}
    print('ports in', dcp, ':', ' '.join(f'{nn}_{n}' for n, nn in sorted(num_by_name.items(), key=lambda kv: kv[1])))
    rc = 0
    for path in files:
        s = open(path).read(); changed = set()
        def sub(m):
            old, name = m.group(1), m.group(2)
            if name not in num_by_name: return m.group(0)
            if num_by_name[name] != old: changed.add(f'{old}->{num_by_name[name]} {name}')
            return f'ctrlind_{num_by_name[name]}_{name}'
        s2 = re.sub(r'(?<![\w])ctrlind_(\d\d)_(\w+)', sub, s)   # not the _ctrlind_ inside bd net labels
        if s2 != s: open(path, 'w').write(s2)
        print(f'{path}: {len(changed)} renumbered' + (': ' + ', '.join(sorted(changed)) if changed else ''))
    if check:
        w = {name: nn for nn, name in dict(re.findall(r'ctrlind_(\d\d)_(\w+)', open(check).read())).items()}
        if w != num_by_name:
            diff = [f'{n}: wrapper {w.get(n)} dcp {num_by_name.get(n)}' for n in sorted(set(w) | set(num_by_name)) if w.get(n) != num_by_name.get(n)]
            print(f'WRAPPER MISMATCH {check}: ' + '; '.join(diff)); rc = 1
        else:
            print(f'wrapper {check} matches the dcp')
    sys.exit(rc)

if __name__ == '__main__':
    main()
