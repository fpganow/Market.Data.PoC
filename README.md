# Market.Data.PoC
Putting it all together into a Proof-of-Concept
=======

## WARNING: Git Submodules

The parser, filter, and common LabVIEW code now live directly in this repo under
`submodules/`. The only remaining git submodule is `cboe_pitch/` (Python PITCH tooling,
tracks branch `dev`). If you cloned without ```--recurse-submodules```, you need to run:
```
git submodule update --init --recursive
```

## Hardware
Kria KR260 Robotics Starter Kit
https://www.amd.com/en/products/system-on-modules/kria/k26/kr260-robotics-starter-kit.html

## Summary

```
                                             +--- Config --+
                                             |             |
10Gigabit <---- [Market Data / BATS] ----> Parser ----> Filter ---->
```

## LabVIEW Dependencies

* Cluster Toolkit by Autotestware
  * https://www.vipm.io/package/autotestware_lib_cluster_toolkit/

## Usage:

### Build Market.Data.Common

Open the project
Will store all vi's in:
```
submodules/builds/fpganow.common
```

### Vivado
Open Vivado 2021.1
Open TCL Console
cd C:/work/git/fpganow/Market.Data.PoC/vivado
