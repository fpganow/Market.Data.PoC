# Market.Data.PoC
Putting it all together into a Proof-of-Concept
=======

## WARNING: Git Submodules

If you cloned without ```--recurse-submodules```, you need to run:
```
git submodule update --init --recursive --remote
```

## Hardware
Kria KR260 Robotics Starter Kit
https://www.amd.com/en/products/system-on-modules/kria/k26/kr260-robotics-starter-kit.html

## Summary


                                                         Config
                                             |             |
10Gigabit <---- [Market Data / BATS] ----> Parser ----> Filter ---->

## Dependencies

Cluster Toolkit by Autotestware

## Usage:

### Build Market.Data.Common

Open the project
Will store all vi's in:
```
submodules/builds/fpganow.common
```
