project('dpdk-l3fwd-to-docaflow', 'c', version: '0.1.0',
        default_options: ['c_std=c11', 'warning_level=3', 'werror=true'])
inc = include_directories('src')
core = static_library('forward', 'src/forward.c', include_directories: inc)
unit = executable('test-forward', 'tests/test_forward.c', link_with: core,
                  include_directories: inc)
test('forwarding-core', unit)
