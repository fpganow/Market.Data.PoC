/******************************************************************************
* Copyright (C) 2023 Advanced Micro Devices, Inc. All Rights Reserved.
* SPDX-License-Identifier: MIT
******************************************************************************/
/*
 * helloworld.c: simple test application
 *
 * This application configures UART 16550 to baud rate 9600.
 * PS7 UART (Zynq) is not initialized by this application, since
 * bootrom/bsp configures it to baud rate 115200
 *
 * ------------------------------------------------
 * | UART TYPE   BAUD RATE                        |
 * ------------------------------------------------
 *   uartns550   9600
 *   uartlite    Configurable only in HW design
 *   ps7_uart    115200 (configured by bootrom/bsp)
 */

#include <stdio.h>
#include "platform.h"
#include "xparameters.h"

#include "dma_test.h"
#include "fifo_test.h"

int main()
{
	int status = 0;

    init_platform();

    // Test #1
    //   - Make sure KR260 Hardware is working by running a DMA
    //     Loopback test on DMA_1
    printf("** Test #1 - AXI_DMA_1 Loopback() **\n");
    status = dma_loopback_single(XPAR_AXI_DMA_1_DEVICE_ID);
    if (status != XST_SUCCESS) {
    	printf("  ** Test #1 FAILED %d**\n", status);
    }
    printf("  ** Test #1 PASSED **\n");
//    test_single_fifo_loopback(XPAR_AXI_FIFO_0_DEVICE_ID);
//    test_single_fifo_loopback(XPAR_AXI_FIFO_0_DEVICE_ID);

    // Remember to manually reset the kr260
    // Verify network connectivity by reading from rx_data_fifo on dma_0
    int device_id = XPAR_AXI_DMA_0_DEVICE_ID;
//    listen_to_dma(device_id);

    // Look at Market.Data.PoC/vivado/arty_z7 sdk code
    fifo_busy_wait(60);

    cleanup_platform();

    return 0;
}
