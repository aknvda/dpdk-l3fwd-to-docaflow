/* SPDX-License-Identifier: BSD-3-Clause */
#include "options.h"
#include <assert.h>
#include <stdio.h>

int main(void)
{
    const char *good[] = {"app", "--lcores", "0@1", "--no-huge", "--no-pci",
        "-m", "256", "--vdev", "net_pcap0,rx_pcap=/tmp/in.pcap,tx_pcap=/tmp/out.pcap"};
    assert(l3_eal_validate(9, good, 0) == 0);
    const char *bad[] = {"--allow=0000:00:01.0", "-a0000:00:01.0", "--allo=0000:00:01.0",
        "--vdev=net_pcap0,iface=eth0", "--vdev=net_pcap0,rx_iface=eth0,tx_iface=eth0",
        "--vdev=net_pcap0,rx_pcap=in,tx_pcap=out,iface=eth0",
        "--vdev=net_pcap0,rx_pcap=in,rx_pcap=again,tx_pcap=out", "--vdev=net_pcap0",
        "--vdev=net_tap0", "--vdev=net_pcapx,rx_pcap=in,tx_pcap=out",
        "--v=net_pcap0,iface=eth0", "--proc-type=secondary", "-d/tmp/driver.so"};
    for (unsigned i = 0; i < sizeof(bad)/sizeof(bad[0]); ++i) {
        const char *args[] = {"app", bad[i]};
        assert(l3_eal_validate(2, args, 0) != 0);
    }
    assert(l3_eal_validate(9, good, 1) != 0);
    const char *missing[] = {"app", "--lcores"};
    assert(l3_eal_validate(2, missing, 0) != 0);
    puts("EAL admission tests: PASS");
}
