/* SPDX-License-Identifier: BSD-3-Clause */
#ifndef L3_DEVICE_H
#define L3_DEVICE_H
struct doca_dev;
struct ifaddrs;
int l3_pci_valid(const char *pci);
int l3_device_safe(const char *pci);
/* Dependency injection for admission tests; production always uses /sys. */
int l3_device_safe_at(const char *pci, const char *sysfs, const struct ifaddrs *addresses);
int l3_devices_open(const char *pci[2], struct doca_dev *devices[2]);
int l3_devices_close(struct doca_dev *devices[2]);
#endif
