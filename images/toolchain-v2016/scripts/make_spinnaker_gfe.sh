#!/bin/bash

cd spinnaker_tools
source setup
make clean
make || exit $?
cd ..

cd spinn_common
make clean
make || exit $?
make install
cd ..

cd SpiNNMan/c_models/reinjector
make || exit $?
cd ../../..

cd SpiNNFrontEndCommon/c_common/front_end_common_lib
make install-clean
cd ..
make clean
make || exit $?
make install
cd ../..

cd SpiNNakerGraphFrontEnd/spinnaker_graph_front_end/examples
make clean
make || exit $?
cd ../../..
