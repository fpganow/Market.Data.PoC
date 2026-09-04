# Market.Data.Common
Set of Utilities / Common vi's for Market Data Related Projects

## Used by

### CBOE/BATS Pitch Parser
- https://github.com/fpganow/Market.Data.Bats.Parser

### Message Filter
- https://github.com/fpganow/Market.Data.Filter

## Set Up
Clone this repository into the parent directory of the other components, i.e.
```
mkdir /mnt/c/fpganow
cd /mnt/c/fpganow
git clone git@github.com:fpganow/Market.Data.Common.git
git clone git@github.com:fpganow/Market.Data.Bats.Parser.git
git clone git@github.com:fpganow/Market.Data.Filter.git
```

Then open the MarketData.Common project in LabVIEW, and run build on both the host and fpga build specification.  You can then find 2 lvlibs in the 'builds' directory:

```
/mnt/c/fpganow/builds/
. . . . . . . . . . . fpganow.common/fpganow.common.fpga.lvlib
. . . . . . . . . . . . . . . . . . /fpganow.common.host.lvlib
```

More details on how your projects can be structured:
```
/mnt/c/fpganow/Market.Data.Common/
. . . . . . . . . . . Market.Data.common.lvproj
. . . . . . . . . . . /host
. . . . . . . . . . . /fpga
/mnt/c/fpganow/Market.Data.Bats.Parser/
. . . . . . . . . . . Market.Data.Bats.Parser.lvproj
. . . . . . . . . . . /host
. . . . . . . . . . . /fpga
/mnt/c/fpganow/Market.Data.Bats.Filter/
. . . . . . . . . . . Market.Data.Filter.lvproj
. . . . . . . . . . . /host
. . . . . . . . . . . /fpga
```
