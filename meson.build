project('dpdk-l3fwd-to-docaflow', 'c', version: '0.1.0',
        default_options: ['c_std=c11', 'warning_level=3', 'werror=true'])
add_project_arguments('-D_GNU_SOURCE', language: 'c')
inc = include_directories('src')
core = static_library('forward', 'src/forward.c', include_directories: inc)
unit = executable('test-forward', 'tests/test_forward.c', link_with: core,
                  include_directories: inc)
test('forwarding-core', unit)
options = static_library('options', 'src/options.c', include_directories: inc)
options_test = executable('test-options', 'tests/test_options.c', link_with: options,
                          include_directories: inc)
test('eal-admission', options_test)
device_test = executable('test-device', ['tests/test_device.c', 'src/device.c'],
                         include_directories: inc)
test('device-admission', device_test)
netstate_test = executable('test-netstate', 'tests/test_netstate.c', include_directories: inc)
test('kernel-port-restoration', netstate_test)

doca = dependency('doca-flow', version: ['>=3.3', '<3.4'], required: get_option('doca'))
app_deps = [dependency('libdpdk')]
app_sources = ['src/main.c', 'src/device.c', 'src/netstate.c']
app_flags = []
app_link_args = []
app_rpath = ''
if doca.found()
    app_deps += [doca, dependency('doca-common'), dependency('doca-dpdk-bridge')]
    app_sources += 'src/flow.c'
    app_flags += ['-DL3_HAVE_DOCA', '-DDOCA_ALLOW_EXPERIMENTAL_API']
    completion_test = executable('test-flow-completion', 'tests/test_flow_completion.c',
        include_directories: inc, dependencies: [doca, dependency('doca-common')], c_args: app_flags,
        link_args: '-Wl,--wrap=doca_flow_entries_process')
    test('doca-completion-faults', completion_test)
else
    app_sources += 'src/flow_stub.c'
    # Explicitly retain these PMDs when testing against an uninstalled DPDK
    # build. This avoids both system-wide installation and static dependencies
    # unrelated to packet I/O (e.g. libpcap's private D-Bus dependencies).
    pmd_dir = get_option('pcap_driver_dir')
    if pmd_dir != ''
        app_link_args += ['-Wl,--push-state,--no-as-needed',
                         pmd_dir / 'librte_net_pcap.so',
                         pmd_dir / 'librte_mempool_ring.so', '-Wl,--pop-state']
        app_rpath = pmd_dir
    endif
endif
executable('l3fwd-docaflow', app_sources, include_directories: inc,
           link_with: [core, options], dependencies: app_deps, c_args: app_flags,
           link_args: app_link_args, build_rpath: app_rpath)
