#!/usr/bin/env python3
"""Emit the AIXML for compress.buffer.generated.vi (todo.txt item 3, Fix A).

    python3 gen_compress_buffer_vi.py <out.xml>

Same connector pane as compress.buffer.vi (pattern 4815: buffer 11, buffer.length 10,
start.idx 9 -> buffer.out 3, buffer.length.out 2) so bats.parser.vi can take it as a
drop-in replacement.  What it computes (see ip_export/netlist_sim/parser_model.py and the
prototype that was checked against both test pcaps, scratch compress_fix_proto.py):

    diff = buffer.length - start.idx              -> buffer.length.out
    s    = start.idx AND 7      (Remainder.idx)   byte offset inside the first word
    widx = start.idx >> 3       (Word)            first word of the remainder
    w0..w3 = buffer[widx .. widx+3]               Index Array; past the end -> 0
    raw_k = s == 0 ? w_k : (w_k << 8s) OR (w_k+1 >> 8(8-s))      k = 0, 1, 2
    mask_k = diff >= 8(k+1) ? all ones
           : diff <= 8k      ? 0
           : all ones << 8*(8(k+1) - diff)        i.e. the top (diff - 8k) bytes
    buffer.out[k] = raw_k AND mask_k ; buffer.out[3..8] = 0

The original VI only produced buffer.out[0] and sized its second-word mask with
buffer.length AND 7, which is wrong as soon as the remainder is longer than 8 bytes
(a message that was already complete before this cycle's word arrived).  Shift amounts
never reach 64 (the masks for diff on a word boundary are chosen with Select), so no
assumption about Logical Shift saturating is needed.
"""
import sys

ALL1 = "18446744073709551615"


def main(out):
    L = []
    a = L.append
    a('<VI _name="compress.buffer.generated.vi" description="Drop start.idx bytes from the front of buffer and move the remaining buffer.length - start.idx bytes to the top of buffer.out (byte 0 in the MSB of word 0). Rebuilds output words 0..2 (remainders up to 24 bytes) and masks every byte at or beyond the new length, so a remainder longer than one word after an already-complete message is preserved. Replaces compress.buffer.vi, which rebuilt word 0 only.">')
    # ---- controls / shared constants
    a('  <Control _name="buffer" conIdx="11" connection="recommended" outputs="value:67.value" type="array{uint64.Numeric}" uid="67" uid_parent="root" value="[4822678189205111,0,0,0,0,0,0,0,0]"/>')
    a('  <Control _name="buffer.length" conIdx="10" connection="recommended" outputs="value:467.value" type="uint8" uid="467" uid_parent="root" value="8"/>')
    a('  <Control _name="start.idx" conIdx="9" connection="recommended" outputs="value:520.value" type="uint8" uid="520" uid_parent="root" value="0"/>')
    a('  <Constant _name="y" outputs="value:100.value" type="uint8" uid="100" uid_parent="root" value="7"/>')
    a('  <Constant _name="y" outputs="value:101.value" type="int16" uid="101" uid_parent="root" value="-3"/>')
    a('  <Constant _name="buffer.out 2" outputs="value:102.value" type="array{uint64.Numeric}" uid="102" uid_parent="root" value="[0,0,0,0,0,0,0,0,0]"/>')
    a(f'  <Constant _name="all ones" outputs="value:190.value" type="uint64" uid="190" uid_parent="root" value="{ALL1}"/>')
    a('  <Constant _name="y" outputs="value:191.value" type="int16" uid="191" uid_parent="root" value="3"/>')
    a('  <Constant _name="zero" outputs="value:192.value" type="uint64" uid="192" uid_parent="root" value="0"/>')
    a('  <Constant _name="index" outputs="value:193.value" type="int32" uid="193" uid_parent="root" value="1"/>')
    a('  <Constant _name="index" outputs="value:194.value" type="int32" uid="194" uid_parent="root" value="2"/>')
    # ---- diff, s, widx, w0..w3
    a('  <FreeLabel comment="diff = buffer.length - start.idx = bytes left after the consumed message\\0As = start.idx AND 7 = byte offset of the first remaining byte inside its word\\0Awidx = start.idx &gt;&gt; 3 = index of the word holding the first remaining byte\\0Aw0..w3 = buffer[widx .. widx+3]  (an index past the end of the array reads as 0)" uid="105" uid_parent="root"/>')
    a('  <Node _name="Subtract" comment="diff" inputs="x:467.value,y:520.value" outputs="x-y:110.diff" uid="110" uid_parent="root"/>')
    a('  <Node _name="And" comment="s" inputs="x:520.value,y:100.value" outputs="x .and. y?:111.s" uid="111" uid_parent="root"/>')
    a('  <Node _name="Logical Shift" comment="widx" inputs="y:101.value,x:520.value" outputs="x &lt;&lt; y:112.widx" uid="112" uid_parent="root"/>')
    a('  <Node _name="Equal To 0?" comment="remainder starts on a word boundary?" inputs="x:111.s" outputs="x = 0?:113.aligned" uid="113" uid_parent="root"/>')
    a('  <Node _name="Index Array" comment="w0 w1 w2 w3" inputs="array:67.value,index:112.widx,index:,index:,index:" outputs="element:114.w0,element:114.w1,element:114.w2,element:114.w3" uid="114" uid_parent="root"/>')
    a('  <Indicator _name="Remainder.idx" inputs="value:111.s" type="uint8" uid="120" uid_parent="root" value="0"/>')
    a('  <Indicator _name="Word" inputs="value:112.widx" type="uint8" uid="121" uid_parent="root" value="0"/>')
    # ---- case: aligned / unaligned -> raw0..raw2
    a('  <Structure _name="Case Structure" selectin="113.aligned" uid="200" uid_parent="root">')
    for i, net in enumerate(("114.w0", "114.w1", "114.w2", "114.w3", "111.s"), 1):
        a(f'    <Tunnel _id="In{i}" inputs="value:{net}" uid="{200 + i}" uid_parent="200"/>')
    # False frame: unaligned
    a('    <CaseFrame selector="False" selectout="" uid="210" uid_parent="200">')
    a('      <FreeLabel comment="Remainder not word-aligned (s = 1..7):\\0Araw_k = (w_k &lt;&lt; 8s) OR (w_k+1 &gt;&gt; 8(8-s))  for k = 0 1 2\\0Athe same two shifts the old VI did for w0/w1 only\\2C repeated for w1/w2 and w2/w3" uid="216" uid_parent="210"/>')
    for i in range(1, 6):
        a(f'      <Tunnel _id="In{i}" outputs="value:{210 + i}.value" uid="{210 + i}" uid_parent="210"/>')
    a('      <Constant _name="y" outputs="value:220.value" type="int16" uid="220" uid_parent="210" value="3"/>')
    a('      <Constant _name="x" outputs="value:221.value" type="uint8" uid="221" uid_parent="210" value="8"/>')
    a('      <Constant _name="y" outputs="value:222.value" type="int16" uid="222" uid_parent="210" value="3"/>')
    a('      <Node _name="Logical Shift" comment="8*s" inputs="y:220.value,x:215.value" outputs="x &lt;&lt; y:230.s8" uid="230" uid_parent="210"/>')
    a('      <Node _name="To Word Integer" comment="shift left amount" inputs="number:230.s8" outputs="16bit integer:231.shl" uid="231" uid_parent="210"/>')
    a('      <Node _name="Subtract" comment="8-s" inputs="x:221.value,y:215.value" outputs="x-y:232.ems" uid="232" uid_parent="210"/>')
    a('      <Node _name="Logical Shift" comment="8*(8-s)" inputs="y:222.value,x:232.ems" outputs="x &lt;&lt; y:233.ems8" uid="233" uid_parent="210"/>')
    a('      <Node _name="To Word Integer" inputs="number:233.ems8" outputs="16bit integer:234.ems16" uid="234" uid_parent="210"/>')
    a('      <Node _name="Negate" comment="shift right amount" inputs="x:234.ems16" outputs="-x:235.shr" uid="235" uid_parent="210"/>')
    for k in range(3):
        b = 240 + 3 * k
        a(f'      <Node _name="Logical Shift" comment="w{k} &lt;&lt; 8s" inputs="y:231.shl,x:{211 + k}.value" outputs="x &lt;&lt; y:{b}.hi" uid="{b}" uid_parent="210"/>')
        a(f'      <Node _name="Logical Shift" comment="w{k + 1} &gt;&gt; 8(8-s)" inputs="y:235.shr,x:{212 + k}.value" outputs="x &lt;&lt; y:{b + 1}.lo" uid="{b + 1}" uid_parent="210"/>')
        a(f'      <Node _name="Or" comment="raw{k}" inputs="x:{b}.hi,y:{b + 1}.lo" outputs="x .or. y?:{b + 2}.raw" uid="{b + 2}" uid_parent="210"/>')
        a(f'      <Tunnel _id="Out{k + 1}" inputs="value:{b + 2}.raw" uid="{250 + k}" uid_parent="210"/>')
    a('    </CaseFrame>')
    # True frame: aligned
    a('    <CaseFrame selector="True" selectout="" uid="260" uid_parent="200">')
    a('      <FreeLabel comment="Remainder starts on a word boundary (s = 0):\\0Araw_k = w_k" uid="266" uid_parent="260"/>')
    for i in range(1, 4):
        a(f'      <Tunnel _id="In{i}" outputs="value:{260 + i}.value" uid="{260 + i}" uid_parent="260"/>')
    a('      <Tunnel _id="In4" outputs="value:" uid="264" uid_parent="260"/>')
    a('      <Tunnel _id="In5" outputs="value:" uid="265" uid_parent="260"/>')
    for k in range(3):
        a(f'      <Tunnel _id="Out{k + 1}" inputs="value:{261 + k}.value" uid="{270 + k}" uid_parent="260"/>')
    a('    </CaseFrame>')
    for k in range(3):
        a(f'    <Tunnel _id="Out{k + 1}" outputs="value:{280 + k}.raw" uid="{280 + k}" uid_parent="200"/>')
    a('  </Structure>')
    # ---- masks and output words
    a('  <FreeLabel comment="Byte j of the output is valid only while j &lt; diff. For output word k (k = 0 1 2):\\0A  diff &gt;= 8(k+1)  -&gt; keep the whole word (mask all ones)\\0A  diff &lt;= 8k      -&gt; nothing left for this word (mask 0)\\0A  otherwise        -&gt; keep the top (diff - 8k) bytes: all ones &lt;&lt; 8*(8(k+1) - diff)\\0AThe old VI sized this mask with buffer.length AND 7\\2C which only works while diff &lt;= 8." uid="299" uid_parent="root"/>')
    for k in range(3):
        b = 300 + 20 * k
        hi = 8 * (k + 1)
        a(f'  <Constant _name="y" outputs="value:{b + 1}.value" type="uint8" uid="{b + 1}" uid_parent="root" value="{hi}"/>')
        a(f'  <Node _name="Greater Or Equal?" comment="diff &gt;= {hi}: whole word {k} valid" inputs="x:110.diff,y:{b + 1}.value" outputs="x &gt;= y?:{b + 2}.full" uid="{b + 2}" uid_parent="root"/>')
        if k == 0:
            a(f'  <Node _name="Equal To 0?" comment="diff = 0: nothing left" inputs="x:110.diff" outputs="x = 0?:{b + 3}.none" uid="{b + 3}" uid_parent="root"/>')
        else:
            a(f'  <Constant _name="y" outputs="value:{b + 11}.value" type="uint8" uid="{b + 11}" uid_parent="root" value="{8 * k}"/>')
            a(f'  <Node _name="Less Or Equal?" comment="diff &lt;= {8 * k}: nothing left for word {k}" inputs="x:110.diff,y:{b + 11}.value" outputs="x &lt;= y?:{b + 3}.none" uid="{b + 3}" uid_parent="root"/>')
        a(f'  <Node _name="Subtract" comment="{hi} - diff" inputs="x:{b + 1}.value,y:110.diff" outputs="x-y:{b + 4}.rem" uid="{b + 4}" uid_parent="root"/>')
        a(f'  <Node _name="Logical Shift" comment="*8" inputs="y:191.value,x:{b + 4}.rem" outputs="x &lt;&lt; y:{b + 5}.rem8" uid="{b + 5}" uid_parent="root"/>')
        a(f'  <Node _name="To Word Integer" inputs="number:{b + 5}.rem8" outputs="16bit integer:{b + 6}.sh" uid="{b + 6}" uid_parent="root"/>')
        a(f'  <Node _name="Logical Shift" comment="top (diff-{8 * k}) bytes" inputs="y:{b + 6}.sh,x:190.value" outputs="x &lt;&lt; y:{b + 7}.mid" uid="{b + 7}" uid_parent="root"/>')
        a(f'  <Node _name="Select" inputs="t:192.value,s:{b + 3}.none,f:{b + 7}.mid" outputs="s? t\\3Af:{b + 8}.m1" uid="{b + 8}" uid_parent="root"/>')
        a(f'  <Node _name="Select" inputs="t:190.value,s:{b + 2}.full,f:{b + 8}.m1" outputs="s? t\\3Af:{b + 9}.mask" uid="{b + 9}" uid_parent="root"/>')
        a(f'  <Node _name="And" comment="buffer.out[{k}]" inputs="x:{280 + k}.raw,y:{b + 9}.mask" outputs="x .and. y?:{b + 10}.out" uid="{b + 10}" uid_parent="root"/>')
        a(f'  <Indicator _name="Mask {k}" inputs="value:{b + 9}.mask" type="uint64" uid="{b + 12}" uid_parent="root" value="0"/>')
    a('  <Node _name="Replace Array Subset" comment="word 0" inputs="array:102.value,index:,new element/subarray:310.out" outputs="output array:400.arr" uid="400" uid_parent="root"/>')
    a('  <Node _name="Replace Array Subset" comment="word 1" inputs="array:400.arr,index:193.value,new element/subarray:330.out" outputs="output array:401.arr" uid="401" uid_parent="root"/>')
    a('  <Node _name="Replace Array Subset" comment="word 2" inputs="array:401.arr,index:194.value,new element/subarray:350.out" outputs="output array:402.arr" uid="402" uid_parent="root"/>')
    a('  <Indicator _name="buffer.out" conIdx="3" connection="recommended" inputs="value:402.arr" type="array{uint64.Numeric}" uid="573" uid_parent="root" value="[0,0,0,0,0,0,0,0,0]"/>')
    a('  <Indicator _name="buffer.length.out" conIdx="2" connection="recommended" inputs="value:110.diff" type="uint8" uid="706" uid_parent="root" value="0"/>')
    a('</VI>')
    open(out, "w", newline="\n").write("\n".join(L) + "\n")


if __name__ == "__main__":
    main(sys.argv[1])
